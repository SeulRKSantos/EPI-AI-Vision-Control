import cv2
import numpy as np

# 1. Carregar configuração, pesos e classes
cfg_path = "yolov4_custom.cfg"
weights_path = "yolov4_custom_best.weights"
names_path = "obj.names"  # Arquivo de texto contendo 1 classe por linha

with open(names_path, "r") as f:
    classes = [line.strip() for line in f.readlines()]

# Gerar cores distintas para cada classe
colors = np.random.uniform(0, 255, size=(len(classes), 3))

# 2. Carregar a rede neural no módulo dnn do OpenCV
net = cv2.dnn.readNetFromDarknet(cfg_path, weights_path)

# (Opcional) Descomente se tiver OpenCV compilado com suporte a CUDA
# net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
# net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)

# Obter as camadas de saída do modelo YOLO
layer_names = net.getLayerNames()
output_layers = [layer_names[i - 1] for i in net.getUnconnectedOutLayers().flatten()]

# 3. Iniciar captura de vídeo da Webcam integrada (índice 0)
cap = cv2.VideoCapture(0)

CONF_THRESHOLD = 0.1   # Limite de confiança mínima
NMS_THRESHOLD = 0.1    # Limite para supressão de não-máximos (IoU)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    height, width, _ = frame.shape

    # Pré-processamento: normalização e redimensionamento para o YOLO (416x416 padrão)
    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (416, 416), swapRB=True, crop=False)
    net.setInput(blob)
    outputs = net.forward(output_layers)

    boxes = []
    confidences = []
    class_ids = []

    for output in outputs:
        for detection in output:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]

            if confidence > CONF_THRESHOLD:
                center_x = int(detection[0] * width)
                center_y = int(detection[1] * height)
                w = int(detection[2] * width)
                h = int(detection[3] * height)

                x = int(center_x - w / 2)
                y = int(center_y - h / 2)

                boxes.append([x, y, w, h])
                confidences.append(float(confidence))
                class_ids.append(class_id)

    # Filtrar caixas sobrepostas
    indices = cv2.dnn.NMSBoxes(boxes, confidences, CONF_THRESHOLD, NMS_THRESHOLD)

    if len(indices) > 0:
        for i in indices.flatten():
            x, y, w, h = boxes[i]
            nome_classe = classes[class_ids[i]]
            confianca = confidences[i]

            # Exibe o objeto detectado no terminal
            print(f"Detectado: {nome_classe} ({confianca:.2%})")

            label = f"{nome_classe}: {confianca:.2f}"
            color = colors[class_ids[i]]

            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, label, (x, max(y - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    cv2.imshow("Deteccao YOLOv4 - Webcam", frame)

    # Pressione 'q' para fechar a janela
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()