/**
 * State machine tests.
 *
 * Run on the desktop, no board required:
 *   g++ -std=c++17 -I../../src test_main.cpp ../../src/access_state.cpp -o t && ./t
 *
 * The emphasis is on the paths that must never open the lock.
 */

#include <cstdio>
#include <cstring>

#include "access_state.h"

using namespace gate;

static int failures = 0;
static int checks = 0;

#define CHECK(cond, name)                                        \
  do {                                                           \
    ++checks;                                                    \
    if (!(cond)) {                                               \
      std::printf("  FALHOU: %s  (linha %d)\n", name, __LINE__); \
      ++failures;                                                \
    }                                                            \
  } while (0)

static Config test_config() {
  Config c;
  c.decision_timeout_ms = 10000;
  c.unlock_duration_ms = 5000;
  c.denied_display_ms = 3000;
  c.badge_cooldown_ms = 5000;
  return c;
}

/// A machine already online and idle, which is the usual starting point.
static StateMachine online_machine(uint32_t now = 0) {
  StateMachine m(test_config());
  m.on_connectivity(true, now);
  return m;
}

// --- Happy path ----------------------------------------------------------

static void test_grant_opens_and_relocks() {
  auto m = online_machine();

  auto out = m.on_badge("BADGE001", 1000);
  CHECK(out.publish_scan, "leitura publica o scan");
  CHECK(m.state() == State::AwaitingDecision, "vai para aguardando decisao");

  out = m.on_decision(m.current_session(), true, 1500);
  CHECK(out.action == Action::Unlock, "decisao liberada destranca");
  CHECK(m.state() == State::Granted, "estado liberado");

  out = m.tick(3000);
  CHECK(out.action == Action::None, "nao retranca antes do tempo");

  out = m.tick(6500);
  CHECK(out.action == Action::Relock, "retranca ao fim do tempo");
  CHECK(m.state() == State::Idle, "volta a ocioso");
}

static void test_denial_shows_and_returns() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);

  auto out = m.on_decision(m.current_session(), false, 1200);
  CHECK(out.action == Action::ShowDenied, "decisao negada sinaliza recusa");
  CHECK(m.state() == State::Denied, "estado negado");

  out = m.tick(4300);
  CHECK(out.action == Action::ShowIdle, "volta a ocioso apos exibir");
  CHECK(m.state() == State::Idle, "estado ocioso");
}

// --- Paths that must never unlock ---------------------------------------

static void test_timeout_denies() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);

  auto out = m.tick(5000);
  CHECK(out.action == Action::None, "ainda aguardando dentro do prazo");

  out = m.tick(11001);
  CHECK(out.action == Action::ShowDenied, "silencio vira recusa");
  CHECK(m.state() == State::Denied, "nao fica preso aguardando");
}

static void test_late_grant_does_not_unlock() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  const uint32_t token = m.current_session();

  m.tick(11001);  // expira
  CHECK(m.state() == State::Denied, "expirou");

  auto out = m.on_decision(token, true, 11500);
  CHECK(out.action == Action::None, "liberacao atrasada e descartada");
  CHECK(m.state() == State::Denied, "permanece negado");
}

static void test_grant_for_unknown_session_is_ignored() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);

  auto out = m.on_decision(m.current_session() + 99, true, 1200);
  CHECK(out.action == Action::None, "sessao desconhecida e ignorada");
  CHECK(m.state() == State::AwaitingDecision, "segue aguardando a certa");
}

static void test_grant_while_idle_is_ignored() {
  auto m = online_machine();

  auto out = m.on_decision(1, true, 1000);
  CHECK(out.action == Action::None, "liberacao sem leitura nao abre");
  CHECK(m.state() == State::Idle, "permanece ocioso");
}

static void test_duplicate_grant_does_not_reopen() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  const uint32_t token = m.current_session();

  m.on_decision(token, true, 1200);
  auto out = m.on_decision(token, true, 1300);
  CHECK(out.action == Action::None, "segunda liberacao nao reabre");
}

static void test_offline_does_not_read_badges() {
  StateMachine m(test_config());
  CHECK(m.state() == State::Offline, "comeca offline");

  auto out = m.on_badge("BADGE001", 1000);
  CHECK(!out.publish_scan, "offline nao publica");
  CHECK(m.state() == State::Offline, "permanece offline");
}

static void test_disconnect_while_waiting_denies() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);

  auto out = m.on_connectivity(false, 1500);
  CHECK(out.action == Action::ShowDenied, "queda durante espera vira recusa");
  CHECK(m.state() == State::Offline, "vai para offline");

  // E uma decisao que chegue depois nao pode valer.
  out = m.on_decision(1, true, 2000);
  CHECK(out.action == Action::None, "decisao apos queda e ignorada");
}

static void test_disconnect_does_not_cut_an_active_grant() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), true, 1200);

  auto out = m.on_connectivity(false, 1500);
  CHECK(out.action == Action::None, "queda nao interrompe passagem liberada");
  CHECK(m.state() == State::Granted, "mantem liberado ate o fim");

  out = m.tick(6300);
  CHECK(out.action == Action::Relock, "retranca normalmente");
}

// --- Cooldown and concurrency -------------------------------------------

static void test_same_badge_is_ignored_during_cooldown() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), false, 1100);
  m.tick(4200);  // volta a ocioso
  CHECK(m.state() == State::Idle, "ocioso");

  auto out = m.on_badge("BADGE001", 4300);
  CHECK(!out.publish_scan, "mesmo cracha dentro da janela e ignorado");
}

static void test_cooldown_expires() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), false, 1100);
  m.tick(4200);

  auto out = m.on_badge("BADGE001", 6500);
  CHECK(out.publish_scan, "apos a janela o cracha e lido de novo");
}

static void test_cooldown_is_per_badge() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), false, 1100);
  m.tick(4200);

  auto out = m.on_badge("BADGE002", 4300);
  CHECK(out.publish_scan, "outro cracha nao herda a espera do anterior");
}

static void test_badge_during_verification_is_ignored() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);

  auto out = m.on_badge("BADGE002", 1200);
  CHECK(!out.publish_scan, "nova leitura durante verificacao e ignorada");
  CHECK(m.state() == State::AwaitingDecision, "segue na verificacao original");
}

static void test_badge_while_unlocked_is_ignored() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), true, 1200);

  auto out = m.on_badge("BADGE002", 1500);
  CHECK(!out.publish_scan, "nao le cracha com a fechadura aberta");
}

static void test_empty_badge_is_ignored() {
  auto m = online_machine();
  auto out = m.on_badge("", 1000);
  CHECK(!out.publish_scan, "leitura vazia e descartada");
  out = m.on_badge(nullptr, 1000);
  CHECK(!out.publish_scan, "ponteiro nulo e descartado");
}

static void test_sessions_do_not_repeat() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  const uint32_t first = m.current_session();
  m.on_decision(first, false, 1100);
  m.tick(4200);

  m.on_badge("BADGE002", 4300);
  CHECK(m.current_session() != first, "cada verificacao tem sessao propria");
}

static void test_reconnect_returns_to_idle() {
  auto m = online_machine();
  m.on_connectivity(false, 1000);
  CHECK(m.state() == State::Offline, "offline");

  auto out = m.on_connectivity(true, 2000);
  CHECK(out.action == Action::ShowIdle, "reconexao volta a ocioso");
  CHECK(m.state() == State::Idle, "pronto para ler");
}

// --- Clock ordering ------------------------------------------------------

/// The loop reads the clock, then services the network, and a decision that
/// arrives there is stamped a few milliseconds later. A tick carrying the
/// earlier reading must not read as "the whole unlock period has passed".
static void test_tick_stamped_before_the_grant_does_not_relock() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), true, 1530);

  auto out = m.tick(1500);
  CHECK(out.action == Action::None, "tick anterior a liberacao nao retranca");
  CHECK(m.state() == State::Granted, "continua liberado");

  out = m.tick(1530 + 4999);
  CHECK(out.action == Action::None, "ainda dentro do tempo de abertura");

  out = m.tick(1530 + 5000);
  CHECK(out.action == Action::Relock, "retranca ao fim do tempo, contado da liberacao");
}

static void test_tick_stamped_before_the_denial_keeps_it_on_screen() {
  auto m = online_machine();
  m.on_badge("BADGE001", 1000);
  m.on_decision(m.current_session(), false, 1530);

  auto out = m.tick(1500);
  CHECK(out.action == Action::None, "recusa nao some no mesmo instante");
  CHECK(m.state() == State::Denied, "continua mostrando a recusa");
}

static void test_unlock_survives_millis_wraparound() {
  // millis() wraps after about 49.7 days of uptime.
  const uint32_t near_wrap = 0xFFFFFFFFu - 1000;
  auto m = online_machine(near_wrap - 2000);
  m.on_badge("BADGE001", near_wrap - 1000);
  m.on_decision(m.current_session(), true, near_wrap);

  auto out = m.tick(near_wrap + 3000);  // wrapped past zero
  CHECK(out.action == Action::None, "virada do relogio nao retranca cedo");

  out = m.tick(near_wrap + 5000);
  CHECK(out.action == Action::Relock, "retranca no tempo certo apos a virada");
}

int main() {
  std::printf("Maquina de estados do portao\n\n");

  test_grant_opens_and_relocks();
  test_denial_shows_and_returns();
  test_timeout_denies();
  test_late_grant_does_not_unlock();
  test_grant_for_unknown_session_is_ignored();
  test_grant_while_idle_is_ignored();
  test_duplicate_grant_does_not_reopen();
  test_offline_does_not_read_badges();
  test_disconnect_while_waiting_denies();
  test_disconnect_does_not_cut_an_active_grant();
  test_same_badge_is_ignored_during_cooldown();
  test_cooldown_expires();
  test_cooldown_is_per_badge();
  test_badge_during_verification_is_ignored();
  test_badge_while_unlocked_is_ignored();
  test_empty_badge_is_ignored();
  test_sessions_do_not_repeat();
  test_reconnect_returns_to_idle();
  test_tick_stamped_before_the_grant_does_not_relock();
  test_tick_stamped_before_the_denial_keeps_it_on_screen();
  test_unlock_survives_millis_wraparound();

  std::printf("\n%d verificacoes, %d falhas\n", checks, failures);
  return failures == 0 ? 0 : 1;
}
