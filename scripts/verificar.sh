#!/usr/bin/env bash
# Full health check of EPI-AI-Vision-Control: repository, containers,
# services, the gate's connection and every test suite.
#
#   bash scripts/verificar.sh

# Works from the repository root or from scripts/.
cd "$(dirname "$0")" 2>/dev/null || true
[ -f docker-compose.yml ] || cd ..
[ -f docker-compose.yml ] || { echo "Rode dentro do repositorio (onde fica o docker-compose.yml)."; exit 1; }

PASS=0; FAIL=0
ok()   { echo "  [OK]    $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FALHA] $1"; FAIL=$((FAIL+1)); }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }

echo "== Repositorio =="
git fetch -q origin 2>/dev/null
check "branch atual e a main"            '[ "$(git branch --show-current)" = main ]'
check "igual ao GitHub (origin/main)"    '[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]'
check "nada pendente"                    '[ -z "$(git status --porcelain | grep -v verificar.sh)" ]'
check "nenhum segredo versionado"        '! git ls-files | grep -Eq "(^|/)\.env$|include/config\.h$|config\.h\.old"'
check "esqueleto antigo removido"        '! git ls-files firmware | grep -Eq "lock_actuator|mqtt_handler|rfid_reader"'

echo "== Containers =="
for s in mosquitto db backend frontend vision; do
  check "$s rodando" "docker compose ps --status running --services | grep -qx $s"
done

echo "== Servicos =="
# Right after a rebuild the backend is still waiting for the database,
# migrating and connecting to the broker; give it up to 30 s.
API_READY=0
for _ in $(seq 1 15); do
  if curl -fs localhost:8000/health/ready | grep -Eq '"ready": *true'; then API_READY=1; break; fi
  sleep 2
done
if [ "$API_READY" = 1 ]; then ok "API pronta (banco e MQTT)"; else
  bad "API pronta (banco e MQTT): $(curl -s localhost:8000/health/ready || echo 'sem resposta')"; fi
check "painel no ar (porta 3000)"        '[ "$(curl -s -o /dev/null -w "%{http_code}" localhost:3000)" = 200 ]'
check "painel com a aba Visao do portao" 'docker compose exec -T frontend sh -c "grep -lq \"Visão do portão\" /usr/share/nginx/html/assets/*.js"'
check "camera no ar (porta 8081)"        'curl -fs localhost:8081/health'

echo "== Portao (ESP32) =="
STATUS=$(docker compose exec -T mosquitto mosquitto_sub -t 'access/gate-01/status' -C 1 -W 3 2>/dev/null | tr -d '\r')
if [ "$STATUS" = online ]; then ok "gate-01 online no broker"; else bad "gate-01 online no broker (status: ${STATUS:-sem resposta})"; fi

echo "== Testes =="
check "backend (pytest)"                 'docker compose exec -T backend pytest -q'
check "visao: detector"                  'docker compose exec -T vision python tests/test_detector.py'
check "visao: imagem ao vivo"            'docker compose exec -T vision python tests/test_live.py'
if command -v pio >/dev/null 2>&1; then
  check "firmware: maquina de estados"   '(cd firmware/esp32_access_gate && pio test -e native)'
else
  bad "firmware: PlatformIO nao encontrado (pio)"
fi

echo
echo "Resultado: $PASS OK, $FAIL falha(s)"
[ "$FAIL" -eq 0 ]
