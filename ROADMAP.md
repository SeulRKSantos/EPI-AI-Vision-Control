# Roadmap

O que já funciona, o que falta e o que fica como trabalho futuro. A área indicada em cada item é a responsável: **Visão e IA** (`vision/`, `training/`) ou **IoT e Backend** (`backend/`, `frontend/`, `firmware/`).

## Estado atual

O ciclo completo funciona com hardware real: cartão no leitor RC522, ESP32, MQTT, backend, câmera com o modelo do Roboflow, decisão, relé com a fechadura e registro no painel.

| Parte | Situação |
|---|---|
| Backend | Regras de decisão, seis motivos de recusa, sessões com tempo limite, API completa e troca de crachá. 84 testes |
| Painel | Matriz, funcionários, funções, equipamentos, histórico ao vivo, teste do portão e câmera ao vivo com as caixas do modelo |
| Visão | Inferência sob demanda por leitura de crachá, transmissão ao vivo com limite de custo e proteção contra chamadas travadas |
| Firmware | Máquina de estados testada, programa de teste de bancada, fechadura aberta por 20 s, recuperação automática do leitor |
| Infraestrutura | Docker Compose com reinício automático e `scripts/verificar.sh` para checar tudo de uma vez |

## Antes da apresentação

- [ ] **Cadastrar os cartões físicos** — IoT e Backend. Sugestão: um cartão para cada uma das 5 funções, um cadastrado e depois desativado (recusa por funcionário inativo) e um sem cadastro (recusa por crachá desconhecido).
- [ ] **Conferir a matriz da demonstração** — IoT e Backend. O modelo não reconhece colete nem respirador, então esses itens ficam fora da matriz do Operador e do Químico. **Não rode o seed de novo depois disso:** ele restaura a matriz original.
- [ ] **Testar cada função diante da câmera**, com e sem os EPIs, na iluminação da sala da apresentação — Visão e IA.
- [ ] **Escrever o roteiro da demonstração**: acesso liberado, recusa por EPI faltando (mostrando o item na tela), crachá desconhecido, funcionário inativo, e a câmera ao vivo.
- [ ] **Checklist do dia**:
  - `bash scripts/verificar.sh` com tudo ligado (esperado: 19 OK);
  - internet funcionando, porque o modelo roda na nuvem do Roboflow. Sem internet, toda leitura é negada, que é o comportamento seguro, mas a demo trava;
  - nenhum outro programa usando a porta 8081 nem a webcam;
  - ESP32 com o `config.h` apontando para o IP do servidor naquela rede.
- [ ] **Atualizar a proposta e os slides** — ambas as áreas. Eles ainda descrevem YOLO local; o projeto usa um workflow do Roboflow. Incluir também a ligação real do hardware e o painel.

## Hardware da versão final — IoT e Backend

- [ ] **Transistor de interface para o relé**: BC547 (ou 2N2222), 1 kΩ na base e 10 kΩ da base ao GND. O módulo volta para o 5V e o relé deixa de perturbar a alimentação do leitor. No firmware, `RELAY_ACTIVE_LOW = false`.
- [ ] **Capacitores junto ao RC522**: 100 µF + 100 nF entre 3V3 e GND.
- [ ] **Diodo 1N4007** invertido nos terminais da fechadura.
- [ ] **Liberação mecânica pelo lado de dentro** (botão de saída), independente do firmware.
- [ ] **Caixa e fixação** do ESP32, do leitor e da fonte; câmera fixa na altura do peito, com enquadramento conferido pela aba Visão do portão.
- [ ] **Nobreak na fonte de 12 V**, se o portão precisar continuar travado durante queda de energia. Sem ele, a fechadura libera, que é o comportamento de rota de fuga.

## Modelo de visão — Visão e IA

- [ ] **Classes de colete e respirador** no dataset, para devolver esses itens à matriz e cobrir Operador e Químico como a NR-6 pede.
- [ ] **Calibrar o limite de confiança** (`DETECTION_CONFIDENCE_THRESHOLD`, hoje 0,6) com medições reais: taxa de acerto e de falso positivo por item.
- [ ] **Avaliar a classe Rímel** em condições variadas de luz, para confirmar que ela continua absorvendo os falsos "óculos".
- [ ] **Registrar as métricas do modelo** (precisão e recall por classe) no README da visão.
- [ ] **Servidor de inferência local** (container do Roboflow Inference) para funcionar sem internet. O serviço já aceita outro endereço por `ROBOFLOW_API_URL`.

## Backend e painel — IoT e Backend

- [ ] **Identificar o crachá antes de chamar a visão.** Hoje a análise é pedida para qualquer cartão. Checar antes se o funcionário existe e está ativo economiza chamadas e registra o motivo certo: um crachá desconhecido com o serviço de visão fora do ar aparece hoje como "visão sem resposta".
- [ ] **Seed sem sobrescrever**: o seed só deve criar o que não existe, sem restaurar a matriz nem a função de quem já foi alterado.
- [ ] **Status do portão no painel**: o backend já recebe `online`/`offline` do ESP32; falta mostrar isso no cabeçalho.
- [ ] **Exportar o histórico** em CSV para relatórios de segurança do trabalho.
- [ ] **Corrigir o CRLF no Windows**: um `.gitattributes` com `*.sh text eol=lf`, para o backend não ficar reiniciando em quem clona no Windows.
- [ ] **Integração contínua**: GitHub Actions rodando os testes do backend, da visão e do firmware em cada Pull Request.

## Segurança

- [ ] **Trocar a chave do Roboflow.** A atual ficou no histórico do Git em uma versão antiga do código. Gerar uma nova e atualizar só o `.env`.
- [ ] **Login no painel**, com perfis (administrador e consulta). Hoje qualquer pessoa na rede pode alterar a matriz e os funcionários.
- [ ] **Autenticação no broker MQTT**: usuário e senha por dispositivo, com ACL por tópico, e TLS. Hoje o Mosquitto aceita conexões anônimas, e qualquer um na rede poderia publicar uma decisão.
- [ ] **Restringir a porta 5432** do PostgreSQL, hoje aberta para a rede, e restringir o CORS quando o endereço do painel for fixo.

## LGPD

- [ ] **Política de retenção do histórico de acessos**: por quanto tempo os registros ficam guardados e quem pode consultá-los.
- [ ] **Imagens**: manter `SAVE_SNAPSHOTS` desligado por padrão. Se ligado para auditoria, definir prazo de descarte e informar os funcionários sobre a captura.
- [ ] **Aviso de finalidade** na entrada controlada: a câmera verifica EPI e não é usada para monitoramento.

## Trabalho futuro

- Vários portões: o protocolo já separa por `gate_code`; falta cadastro de portões no painel.
- Atualização do firmware pela rede (OTA) e configuração de Wi-Fi sem recompilar.
- Sinal sonoro no portão, além dos LEDs.
- Verificar o tipo do EPI adequado ao risco (classe do capacete, material da luva), que o modelo atual não distingue.
