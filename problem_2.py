# -*- coding: utf-8 -*-
"""Problem-2.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1jzQyJl-wxer88R0XbEhAegp3VojUkVLP
"""

!pip install opencv-python-headless

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as transforms
import cv2
import matplotlib.pyplot as plt
from typing import List, Tuple, Optional

# Diffusion Model for Noise Injection and Feature Extraction
# Define the Diffusion Model class
class DiffusionModel(nn.Module):
    def __init__(self, input_channels: int = 3, time_steps: int = 1000):
        super().__init__()
        self.time_steps = time_steps

        # Encoder: Series of convolutional layers followed by ReLU activations and pooling
        self.encoder = nn.Sequential(
            nn.Conv2d(input_channels, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),  # Used BatchNormalize activations
            nn.ReLU(),
            nn.MaxPool2d(2),  # Downsampling
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU()
        )

        # Decoder: Transpose convolution layers for reconstructing the input
        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2),
            nn.ReLU(),
            nn.Conv2d(128, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.Conv2d(64, input_channels, kernel_size=3, padding=1),
            nn.Sigmoid()  # Used Sigmoid for ensuring outputs are in the range [0, 1]
        )

    def noise_scheduler(self, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        # Added noise to the input based on the timestep
        noise_scale = torch.sqrt(t.view(-1, 1, 1, 1))
        noise = torch.randn_like(x) * noise_scale
        return x + noise

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        # Adding noise
        t = torch.ones(x.shape[0], device=x.device) * 0.5
        noisy_x = self.noise_scheduler(x, t)

        # Encode and decode
        encoded = self.encoder(noisy_x)
        reconstructed = self.decoder(encoded)

        return reconstructed, encoded

# Define the CNN-only model class
class SimpleCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),  # Downsampling
            nn.Conv2d(512, 512, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1))  # Global average pooling
        )
        self.classifier = nn.Sequential(
            nn.Linear(512, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Process through CNN
        cnn_out = self.cnn(x)
        cnn_out = cnn_out.view(cnn_out.size(0), -1)
        return self.classifier(cnn_out)

# Dataset class for loading and preprocessing video data
class VideoDataset(Dataset):
    def __init__(self, video_path: str, sequence_length: int = 16, frame_interval: int = 2):
        self.video_path = video_path
        self.sequence_length = sequence_length
        self.frame_interval = frame_interval
        self.frames = self._load_video()
        print(f"Loaded {len(self.frames)} frames from video")

    def _load_video(self) -> List[np.ndarray]:
        frames = []
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {self.video_path}")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, (224, 224))
            frame = frame / 255.0  # Normalize to [0, 1]
            frames.append(frame)
            if len(frames) >= 300:  # Limit frames for testing
                break
        cap.release()

        # Visualize first few frames
        for i in range(10):
            plt.imshow(frames[i])
            plt.title(f'Frame {i}')
            plt.show()

        return frames

    def __len__(self) -> int:
        return max(0, len(self.frames) - self.sequence_length * self.frame_interval)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        # Extract a sequence of frames
        sequence = [self.frames[idx + i * self.frame_interval] for i in range(self.sequence_length)]
        sequence = torch.FloatTensor(np.stack(sequence)).permute(0, 3, 1, 2)
        label = torch.tensor([0.0])
        return sequence, label

# Pipeline class to integrate diffusion model and SimpleCNN for end-to-end processing
class Pipeline:
    def __init__(self, video_path: str):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        # Initialize models
        self.diffusion = DiffusionModel().to(self.device)
        self.simple_cnn = SimpleCNN().to(self.device)

        # Setup data
        self.dataset = VideoDataset(video_path)
        self.dataloader = DataLoader(
            self.dataset,
            batch_size=4,
            shuffle=False
        )
        print(f"Dataset size: {len(self.dataset)}")

    def extract_features(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, seq_len, channels, height, width = x.shape
        features = []
        for t in range(seq_len):
            frame = x[:, t].to(self.device)
            with torch.no_grad():
                reconstructed, feat = self.diffusion(frame)

                # Visualize reconstructed frames and features
                if t < 10 or t > seq_len - 10:
                    plt.imshow(reconstructed[0].cpu().permute(1, 2, 0))
                    plt.title(f'Reconstructed Frame {t}')
                    plt.show()

                    plt.imshow(feat[0].cpu().mean(dim=0))
                    plt.title(f'Feature Map {t}')
                    plt.show()

                features.append(feat)
        return torch.stack(features, dim=1)

    def predict(self, x: torch.Tensor) -> torch.Tensor:
        # Extract features using the diffusion model
        features = self.extract_features(x)
        # Use only the last feature map for prediction
        with torch.no_grad():
            prediction = self.simple_cnn(features[:, -1])
        # Converting probabilities to binary(for classifying as Class 0 or Class 1)
        binary_prediction = (prediction > 0.5).float()
        print(f"Predicted probabilities: {prediction} --> Binary predictions: {binary_prediction}")
        return binary_prediction

    def inference_on_video(self) -> List[float]:
        predictions = []
        for i, (batch, _) in enumerate(self.dataloader):
            print(f"Processing batch {i+1}/{len(self.dataloader)}", end='\r')
            pred = self.predict(batch.to(self.device))
            predictions.extend(pred.cpu().numpy().tolist())
            # Processing only a few batches for demonstration
            if i >= 5:
                break
        return predictions


def main():
    video_path = "/content/Hyderabad City _ Dallas Center Road and more@Hitech City.mp4"
    pipeline = Pipeline(video_path)
    predictions = pipeline.inference_on_video()
    print("\nPredictions for first few sequences:", predictions[:4])
    # Visualization of predictions
    plt.plot(predictions)
    plt.title('Predicted Probabilities Over Time')
    plt.xlabel('Frame Index')
    plt.ylabel('Probability')
    plt.show()

if __name__ == "__main__":
    main()

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as transforms
import cv2
import matplotlib.pyplot as plt
from typing import List, Tuple, Optional
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

# Define the Diffusion Model class
class DiffusionModel(nn.Module):
    def __init__(self, input_channels: int = 3, time_steps: int = 1000):
        super().__init__()
        self.time_steps = time_steps
        self.encoder = nn.Sequential(
            nn.Conv2d(input_channels, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU()
        )
        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2),
            nn.ReLU(),
            nn.Conv2d(128, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.Conv2d(64, input_channels, kernel_size=3, padding=1),
            nn.Sigmoid()
        )

    def noise_scheduler(self, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        noise_scale = torch.sqrt(t.view(-1, 1, 1, 1))
        noise = torch.randn_like(x) * noise_scale
        return x + noise

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        t = torch.ones(x.shape[0], device=x.device) * 0.5
        noisy_x = self.noise_scheduler(x, t)
        encoded = self.encoder(noisy_x)
        reconstructed = self.decoder(encoded)
        return reconstructed, encoded

# Define the CNN+LSTM model class
class CNNLSTM(nn.Module):
    def __init__(self, input_size: int = 256, hidden_size: int = 256, num_layers: int = 2):
        super().__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(512, 512, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1))
        )
        self.lstm = nn.LSTM(
            input_size=512,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2
        )
        self.classifier = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, timesteps, channels, height, width = x.shape
        cnn_out = [self.cnn(x[:, t]).view(batch_size, -1) for t in range(timesteps)]
        cnn_out = torch.stack(cnn_out, dim=1)
        lstm_out, _ = self.lstm(cnn_out)
        final_features = lstm_out[:, -1]
        return self.classifier(final_features)

# Dataset class for loading and preprocessing video data
class VideoDataset(Dataset):
    def __init__(self, video_path: str, sequence_length: int = 16, frame_interval: int = 2):
        self.video_path = video_path
        self.sequence_length = sequence_length
        self.frame_interval = frame_interval
        self.frames = self._load_video()
        print(f"Loaded {len(self.frames)} frames from video")

    def _load_video(self) -> List[np.ndarray]:
        frames = []
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {self.video_path}")
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, (224, 224))
            frame = frame / 255.0
            frames.append(frame)
            if len(frames) >= 300:
                break
        cap.release()
        for i in range(10):
            plt.imshow(frames[i])
            plt.title(f'Frame {i}')
            plt.show()
        return frames

    def __len__(self) -> int:
        return max(0, len(self.frames) - self.sequence_length * self.frame_interval)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        sequence = [self.frames[idx + i * self.frame_interval] for i in range(self.sequence_length)]
        sequence = torch.FloatTensor(np.stack(sequence)).permute(0, 3, 1, 2)
        label = torch.tensor([0.0])  # Replace with actual labels when available
        return sequence, label

# Pipeline class to integrate diffusion model and CNN+LSTM for end-to-end processing
class Pipeline:
    def __init__(self, video_path: str):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.diffusion = DiffusionModel().to(self.device)
        self.cnn_lstm = CNNLSTM().to(self.device)
        self.dataset = VideoDataset(video_path)
        self.dataloader = DataLoader(self.dataset, batch_size=4, shuffle=False)
        print(f"Dataset size: {len(self.dataset)}")

    def extract_features(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, seq_len, channels, height, width = x.shape
        features = []
        for t in range(seq_len):
            frame = x[:, t].to(self.device)
            with torch.no_grad():
                reconstructed, feat = self.diffusion(frame)
                if t < 10 or t > seq_len - 10:
                    plt.imshow(reconstructed[0].cpu().permute(1, 2, 0))
                    plt.title(f'Reconstructed Frame {t}')
                    plt.show()
                    plt.imshow(feat[0].cpu().mean(dim=0))
                    plt.title(f'Feature Map {t}')
                    plt.show()
                features.append(feat)
        return torch.stack(features, dim=1)

    def predict(self, x: torch.Tensor) -> torch.Tensor:
        features = self.extract_features(x)
        with torch.no_grad():
            prediction = self.cnn_lstm(features)
        binary_prediction = (prediction > 0.5).float()
        print(f"Predicted probabilities: {prediction} --> Binary predictions: {binary_prediction}")
        return binary_prediction

    def inference_on_video(self) -> Tuple[List[float], List[float]]:
        predictions = []
        labels = []
        for i, (batch, label) in enumerate(self.dataloader):
            print(f"Processing batch {i+1}/{len(self.dataloader)}", end='\r')
            pred = self.predict(batch.to(self.device))
            predictions.extend(pred.cpu().numpy().tolist())
            labels.extend(label.cpu().numpy().tolist())
            if i >= 5:
                break
        # Flatten the predictions list
        flat_predictions = [item for sublist in predictions for item in sublist]
        return flat_predictions, labels

    def evaluate_model(self, predictions: List[float], labels: List[float]) -> None:
        # Calculate and print evaluation metrics
        accuracy = accuracy_score(labels, predictions)
        precision = precision_score(labels, predictions)
        recall = recall_score(labels, predictions)
        f1 = f1_score(labels, predictions)
        print(f"Accuracy: {accuracy:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}, F1 Score: {f1:.4f}")

def main():
    video_path = "/content/videoplayback.mp4"
    pipeline = Pipeline(video_path)
    predictions, labels = pipeline.inference_on_video()
    predictions_binary = [1 if pred > 0.5 else 0 for pred in predictions]  # Convert to binary
    print("\nPredictions for first few sequences:", predictions[:4])
    pipeline.evaluate_model(predictions_binary, labels)
    plt.plot(predictions)
    plt.title('Predicted Probabilities Over Time')
    plt.xlabel('Frame Index')
    plt.ylabel('Probability')
    plt.show()

if __name__ == "__main__":
    main()