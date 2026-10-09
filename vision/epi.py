import cv2
from inference_sdk import InferenceHTTPClient, InferenceConfiguration

# Configuração do limiar de confiança (ajuste conforme necessário: 0.20 = 20%)
CONFIDENCE_THRESHOLD = 0.5

# 1. Configurar o cliente da API
client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key="ZxtG8L2lJU3S14zCd7y2"
).configure(InferenceConfiguration(
    api_key_transport="header"
))

# 2. Inicializar a webcam
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Erro ao abrir a webcam.")
    exit()

print("Pressione 'q' na janela de vídeo para sair.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Falha ao capturar imagem da câmera.")
        break

    # 3. Executar o workflow
    result = client.run_workflow(
        workspace_name="igors-workspace-0bkhu",
        workflow_id="epis-v2-logic",
        images={
            "image": frame
        },
        use_cache=True
    )

    # 4. Extrair predições e desenhar as Bounding Boxes
    if isinstance(result, list) and len(result) > 0:
        output = result[0]
        
        # Obtém a lista de predições do dicionário de saída do workflow
        predictions = output.get("predictions", [])
        if isinstance(predictions, dict) and "predictions" in predictions:
            predictions = predictions["predictions"]

        if isinstance(predictions, list):
            for pred in predictions:
                # Extrair classe e dados do retângulo
                class_name = pred.get("class") or pred.get("class_name", "Desconhecido")
                confidence = pred.get("confidence", 0.0)

                # O Roboflow costuma retornar x_center, y_center, width e height
                x_center = pred.get("x")
                y_center = pred.get("y")
                w = pred.get("width")
                h = pred.get("height")

                if all(v is not None for v in [x_center, y_center, w, h]):
                    # Converter de centro (x, y) e dimensões para vértices superior esquerdo e inferior direito
                    x1 = int(x_center - (w / 2))
                    y1 = int(y_center - (h / 2))
                    x2 = int(x_center + (w / 2))
                    y2 = int(y_center + (h / 2))

                    # Desenhar o retângulo na imagem (Cor Verde: BGR -> 0, 255, 0)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

                    # Configurar e desenhar a etiqueta do texto
                    label = f"{class_name} {confidence:.2f}"
                    cv2.putText(
                        frame,
                        label,
                        (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 0, 0),
                        2
                    )

                    print(class_name)

    # Exibir a imagem tratada com as bounding boxes
    cv2.imshow("Webcam - Roboflow Workflow", frame)

    # Pressione 'q' para encerrar o loop
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Liberar a câmera e fechar as janelas
cap.release()
cv2.destroyAllWindows()