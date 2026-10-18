# EPI-AI-Vision-Control

Controle de acesso que só libera o portão quando o funcionário está usando os Equipamentos de Proteção Individual (EPI) exigidos pela sua função. O sistema combina identificação por crachá RFID, visão computacional e uma fechadura eletrônica, e registra cada tentativa para auditoria.

## Como funciona

```
 crachá ─► ESP32 + RC522 ──MQTT──► backend ──MQTT──► serviço de visão ──► câmera + modelo
                ▲                     │  ▲                    │
                │                     │  └──── EPIs vistos ◄──┘
                └──── decisão ◄───────┘
                      (relé + fechadura)        painel web ◄── histórico, matriz, câmera ao vivo
```

1. O funcionário aproxima o crachá do leitor. O ESP32 publica o identificador do cartão no broker MQTT.
2. O backend identifica o funcionário, consulta os EPIs exigidos pela função dele e pede uma análise ao serviço de visão.
3. O serviço de visão captura o quadro mais recente da câmera, roda o modelo e devolve os EPIs reconhecidos, com a confiança de cada um.
4. O backend compara o exigido com o reconhecido, grava o registro de auditoria e publica a decisão.
5. O ESP32 libera a fechadura por 20 s (LED verde) ou mantém o portão travado (LED vermelho).

**A decisão padrão é negar.** Crachá desconhecido, funcionário desativado, EPI faltando, confiança abaixo do limite, câmera sem imagem, serviço de visão sem resposta ou qualquer falha interna resultam em portão travado. A ausência de resposta nunca é interpretada como autorização.

Cada tentativa recebe um identificador de sessão (UUID) que acompanha todas as mensagens. É ele que impede que uma resposta atrasada, duplicada ou de outra tentativa abra o portão.

## Componentes

| Serviço | Pasta | Porta | Função |
|---|---|---|---|
| Painel web | [`frontend/`](frontend/README.md) | 3000 | Administração, histórico, teste do portão e câmera ao vivo |
| Backend (API) | [`backend/`](backend/README.md) | 8000 | Regras de acesso, banco de dados e auditoria. Documentação interativa em `/docs` |
| Serviço de visão | [`vision/`](vision/README.md) | 8081 | Câmera, modelo (Roboflow) e transmissão ao vivo com as caixas de detecção |
| Broker MQTT | `mosquitto/` | 1883 | Mensageria entre portão, backend e visão |
| Banco de dados | — | 5432 | PostgreSQL 16 |
| Firmware do portão | [`firmware/esp32_access_gate/`](firmware/esp32_access_gate/README.md) | — | ESP32 com leitor RC522, relé, fechadura e LEDs |

Todos os serviços do servidor rodam em Docker Compose, com reinício automático.

## Como rodar

Requisitos: Docker com Compose, uma webcam em `/dev/video0` e uma chave do Roboflow.

```bash
git clone https://github.com/SeulRKSantos/EPI-AI-Vision-Control.git
cd EPI-AI-Vision-Control
cp .env.example .env          # preencha senha do banco e chaves do Roboflow
docker compose up -d --build
```

Depois de subir:

- Painel: `http://<ip-do-servidor>:3000`. Funciona de qualquer máquina da rede, sem configurar IP.
- API: `http://<ip-do-servidor>:8000/docs`.
- Verificação completa do sistema: `bash scripts/verificar.sh` (repositório, containers, serviços, portão e testes de todas as partes).

Na primeira subida, o backend cria as tabelas sozinho. Os dados de exemplo (9 tipos de EPI, 5 funções, o portão `gate-01` e 5 funcionários de teste, `BADGE001` a `BADGE005`) são carregados com:

```bash
docker compose exec backend python -m app.db.seed
```

Cuidado ao repetir esse comando: além de criar o que falta, ele **restaura a matriz de exigências das funções de exemplo** aos valores originais. Não rode de novo depois de ajustar a matriz no painel.

Só um processo pode usar a webcam por vez. Feche qualquer outro programa de câmera antes de subir o serviço de visão.

## Painel

| Aba | Para que serve |
|---|---|
| Matriz de exigências | Quais EPIs cada função exige. Alterar aqui muda a regra na hora, sem reiniciar nada |
| Visão do portão | Câmera ao vivo com as caixas do modelo e a lista do que está sendo reconhecido |
| Testar portão | Simula a leitura de um crachá e mostra o resultado item por item, com uma câmera menor ao lado |
| Funcionários | Cadastro, troca de cartão e desativação |
| Funções / Equipamentos | Cadastro de funções e tipos de EPI |
| Histórico de acessos | Todas as tentativas, com motivo da recusa, EPIs vistos e tempo de resposta. Atualiza sozinho |

## Testar sem o hardware

A aba **Testar portão** publica uma leitura de crachá idêntica à do ESP32. Câmera, modelo e regra de decisão rodam de verdade; só o cartão é simulado. Pela API:

```bash
curl -X POST http://localhost:8000/api/v1/gates/gate-01/simulate-scan \
  -H 'Content-Type: application/json' -d '{"badge_id":"BADGE005"}'
```

## Hardware

| Item | Observação |
|---|---|
| ESP32 DevKit | Wi-Fi 2,4 GHz |
| Leitor RFID RC522 | Alimentado em 3,3 V (nunca 5 V) |
| Módulo relé 1 canal (bobina de 5 V) | Hoje alimentado pelo 3V3 do ESP32 (ver abaixo) |
| Fechadura eletromagnética 12 V | Ligada no contato NC do relé: travada enquanto recebe energia |
| Fonte 12 V | Exclusiva da fechadura |
| LEDs verde e vermelho | Com resistores de 220 a 330 Ω |

A ligação completa, o programa de teste de bancada e as constantes de polaridade estão no [README do firmware](firmware/esp32_access_gate/README.md).

Na montagem atual, o módulo de relé é alimentado pelo 3V3 porque a entrada dele, com optoacoplador, não desliga com o nível de 3,3 V do ESP32 quando alimentada em 5 V. Funciona, mas o chaveamento da bobina perturba a alimentação do leitor RFID; o firmware compensa reiniciando o leitor depois de cada abertura. A correção definitiva, com um transistor de interface, está no [ROADMAP](ROADMAP.md).

## Estrutura do repositório

```
EPI-AI-Vision-Control/
├── docker-compose.yml         # Orquestra broker, banco, backend, painel e visão
├── .env.example               # Modelo de configuração (o .env nunca é versionado)
├── backend/                   # FastAPI, SQLAlchemy assíncrono, Alembic, cliente MQTT
├── frontend/                  # Painel React + Vite + Tailwind, servido por nginx
├── vision/                    # Serviço de visão: câmera, Roboflow, transmissão MJPEG
├── firmware/esp32_access_gate # Firmware PlatformIO do ESP32 e programa de teste de bancada
├── mosquitto/config/          # Configuração do broker
├── training/                  # Pipeline e pesos de treinamento do modelo
├── scripts/verificar.sh       # Verificação completa do sistema
└── ROADMAP.md                 # O que falta e próximos passos
```

## Stack

| Camada | Tecnologia |
|---|---|
| Portão | ESP32, RC522, relé, fechadura 12 V — C++ com PlatformIO (MFRC522, PubSubClient, ArduinoJson) |
| Mensageria | MQTT com Eclipse Mosquitto 2, QoS 1 e Last Will |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 assíncrono, asyncpg, Alembic, aiomqtt, pydantic-settings |
| Banco | PostgreSQL 16 |
| Visão | Workflow do Roboflow via `inference-sdk`, OpenCV, aiohttp |
| Painel | React 19, React Router, Vite, Tailwind CSS 3, nginx |
| Infraestrutura | Docker e Docker Compose |

## Testes

| Parte | Como rodar | O que cobre |
|---|---|---|
| Backend | `docker compose exec backend pytest -q` | Regras de decisão, API, sessões e fluxo completo com MQTT. Os testes de integração rodam com `TEST_DATABASE_URL` e `TEST_MQTT_HOST` |
| Visão | `docker compose exec vision python tests/test_detector.py` e `tests/test_live.py` | Mapeamento de classes, imagem ao vivo, limite de custo e chamadas travadas |
| Firmware | `cd firmware/esp32_access_gate && pio test -e native` | Máquina de estados do portão, sem placa |

## Base normativa

A matriz de exigências segue a NR-6 (EPI), com as particularidades da NR-10 (eletricidade), NR-15 (agentes químicos e ruído) e NR-35 (trabalho em altura), além da NR-1 e dos arts. 166 e 167 da CLT. Os dados pessoais do histórico de acesso estão sujeitos à LGPD.

O sistema confirma que um item está presente, não que ele é o adequado ao risco. Ele não distingue um capacete classe B de um comum, nem uma luva nitrílica de uma de couro. É uma camada adicional de controle e não substitui o procedimento de segurança.

## Organização

- **Visão computacional e treinamento do modelo:** `vision/`, `training/`
- **IoT e backend:** `backend/`, `frontend/`, `firmware/`

A branch `main` é protegida: toda alteração entra por Pull Request revisado, e o `CODEOWNERS` define o revisor de cada pasta.
