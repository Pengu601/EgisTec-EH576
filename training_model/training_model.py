import os
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import torch.nn.functional as F

# Import the dataset we just built!
from testing_pipeline import SiameseFingerprintDataset

class SiameseNetwork(nn.Module):
    def __init__(self):
        super(SiameseNetwork, self).__init__()
        
        # A lightweight Convolutional Neural Network designed to run fast on a laptop CPU
        # Input shape: 1 channel (grayscale), 57 height, 70 width
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.LeakyReLU(0.1, inplace=True),
            nn.MaxPool2d(2, 2), 
            
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.LeakyReLU(0.1, inplace=True),
            nn.MaxPool2d(2, 2), 
            
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.LeakyReLU(0.1, inplace=True),
            nn.MaxPool2d(2, 2)  
        )

        self.fc = nn.Sequential(
            nn.Linear(128 * 7 * 8, 512),
            nn.LeakyReLU(0.1, inplace=True),
            nn.Linear(512, 128) 
        )

    def forward_once(self, x):
        output = self.cnn(x)
        output = output.view(output.size()[0], -1) # Flatten
        output = self.fc(output)
        
        # FIX: Force the embedding onto a unit hypersphere
        output = F.normalize(output, p=2, dim=1)
        return output

    def forward(self, input1, input2):
        """Passes BOTH images through the EXACT same weights (Siamese)."""
        output1 = self.forward_once(input1)
        output2 = self.forward_once(input2)
        return output1, output2

class ContrastiveLoss(nn.Module):
    def __init__(self, margin=1.0):
        super(ContrastiveLoss, self).__init__()
        self.margin = margin

    def forward(self, output1, output2, label):
        # Calculate euclidean distance with a stability epsilon
        euclidean_distance = F.pairwise_distance(output1, output2, keepdim=True)
        
        # label == 1.0 means genuine match, label == 0.0 means imposter
        loss_contrastive = torch.mean(
            label * torch.pow(euclidean_distance, 2) +
            (1 - label) * torch.pow(torch.clamp(self.margin - euclidean_distance, min=0.0), 2)
        )
        return loss_contrastive

def train():
    # Detect Hardware Acceleration (CUDA for Nvidia, MPS for Apple Silicon, CPU fallback)
    device = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    print(f"[*] Training on device: {device}")

    # Hyperparameters
    EPOCHS = 10
    BATCH_SIZE = 64
    LEARNING_RATE = 0.0005

    print("[*] Initializing Dataset and DataLoader...")
    # Point this to your unzipped folder
    dataset = SiameseFingerprintDataset(root_dir="E:\\archive\\SOCOFing\\scoofing_data", train=True)
    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=4)

    print("[*] Initializing Network, Loss, and Optimizer...")
    net = SiameseNetwork().to(device)
    criterion = ContrastiveLoss(margin=1.2)  # <-- This is the one that handles the real training!
    optimizer = optim.Adam(net.parameters(), lr=LEARNING_RATE)

    print("\n=== STARTING TRAINING LOOP ===")
    
    for epoch in range(EPOCHS):
        start_time = time.time()
        running_loss = 0.0
        
        # Set network to training mode
        net.train()
        
        for i, (img1, img2, label) in enumerate(dataloader, 0):
            # Move data to GPU/CPU
            img1, img2, label = img1.to(device), img2.to(device), label.to(device)

            # Zero the gradients
            optimizer.zero_grad()

            # Forward pass
            output1, output2 = net(img1, img2)
            
            # Calculate Loss
            loss = criterion(output1, output2, label)
            
            # Backward pass & Optimize
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

            # Print stats every 50 batches
            if i % 50 == 49:
                print(f"[Epoch {epoch + 1}, Batch {i + 1}] Loss: {running_loss / 50:.4f}")
                running_loss = 0.0

        epoch_duration = time.time() - start_time
        print(f"[-] Epoch {epoch + 1} completed in {epoch_duration:.2f} seconds.")

    print("\n[+] Training Complete!")
    
    # Save the trained weights
    os.makedirs("models", exist_ok=True)
    save_path = "models/siamese_fingerprint.pth"
    torch.save(net.state_dict(), save_path)
    print(f"[SUCCESS] Model saved to {save_path}")

if __name__ == "__main__":
    train()