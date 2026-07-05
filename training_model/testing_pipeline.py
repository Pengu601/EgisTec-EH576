import os
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from torchvision.utils import save_image  # <-- NEW IMPORT
from PIL import Image
import random
import glob
import torchvision.transforms.functional as TF
class ZScoreNormalize:
    
        def __call__(self, tensor):
            mean = tensor.mean()
            std = tensor.std()
            # Add a tiny epsilon to prevent division by zero in blank patches
            return (tensor - mean) / (std + 1e-6)

        def __repr__(self):
            return self.__class__.__name__ + '()'
        
class SimulateEgisCapacitiveSensor:
    def __init__(self, blur_kernel=(7, 7), contrast_range=(0.05, 0.10), 
                 gray_baseline=0.45, noise_std=0.002): # <-- LARGER BLUR, TINY NOISE
        self.blur_kernel = blur_kernel
        self.contrast_range = contrast_range
        self.gray_baseline = gray_baseline
        self.noise_std = noise_std

    def __call__(self, img):
        # 1. Heavy Blur: Destroy the sharp optical edges completely to create soft waves
        img = TF.gaussian_blur(img, kernel_size=self.blur_kernel)
        
        # 2. Contrast Compression
        alpha = random.uniform(self.contrast_range[0], self.contrast_range[1])
        img = img * alpha
        
        # 3. Brightness Shift
        img = img + self.gray_baseline
        img = torch.clamp(img, 0.0, 1.0)
        
        # 4. Sensor Static (Reduced dramatically to match the smooth Egis dump)
        noise = torch.randn_like(img) * self.noise_std
        img = img + noise
        
        return torch.clamp(img, 0.0, 1.0)

    def __repr__(self):
        return self.__class__.__name__ + '()'
    
class SiameseFingerprintDataset(Dataset):
    def __init__(self, root_dir, train=True):
        """
        Loads the SOCOFing dataset, explicitly pulling from Real and all Altered subdirectories.
        """
        self.root_dir = root_dir
        self.train = train
        
        # Transform Pipeline: Tensor -> Simulate Capacitive Sensor
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            SimulateEgisCapacitiveSensor(
                blur_kernel=(3, 3),
                contrast_range=(0.08, 0.15), 
                gray_baseline=0.45, 
                noise_std=0.02
            ),
            ZScoreNormalize()  # <-- ADDED HERE
        ])
        
        # Load from all SOCOFing sub-folders
        real_paths = glob.glob(os.path.join(root_dir, "Real", "*.BMP"))
        alt_easy = glob.glob(os.path.join(root_dir, "Altered", "Altered-Easy", "*.BMP"))
        alt_med = glob.glob(os.path.join(root_dir, "Altered", "Altered-Medium", "*.BMP"))
        alt_hard = glob.glob(os.path.join(root_dir, "Altered", "Altered-Hard", "*.BMP"))
        
        self.image_paths = real_paths + alt_easy + alt_med + alt_hard
        
        if not self.image_paths:
            raise FileNotFoundError(f"No BMP files found in {root_dir}. Check your folder structure!")
            
        print(f"[*] Loaded {len(self.image_paths)} total fingerprint images.")

        # Group paths by UNIQUE FINGER to easily pull matches vs imposters
        self.subject_groups = {}
        for path in self.image_paths:
            filename = os.path.basename(path)
            
            # Example filename: "1__M_Left_index_finger_CR.BMP" or "1__M_Left_index_finger.BMP"
            # We want the unique ID to be: "1_Left_index_finger"
            parts = filename.replace(".BMP", "").split("_")
            
            # Extract the core identity (Subject + Hand + Finger Name)
            subject_num = parts[0]
            hand = parts[3] # "Left" or "Right"
            finger_name = parts[4] # "index", "thumb", etc.
            
            unique_finger_id = f"{subject_num}_{hand}_{finger_name}"
            
            if unique_finger_id not in self.subject_groups:
                self.subject_groups[unique_finger_id] = []
            self.subject_groups[unique_finger_id].append(path)
            
        self.subject_ids = list(self.subject_groups.keys())
        print(f"[*] Found {len(self.subject_ids)} unique subjects.")

    def __len__(self):
        # We generate pairs dynamically, so length is arbitrary per epoch
        return 50000 if self.train else 5000

    def __getitem__(self, idx):
        should_match = random.randint(0, 1)
        
        if should_match:
            subject = random.choice(self.subject_ids)
            while len(self.subject_groups[subject]) < 2:
                subject = random.choice(self.subject_ids)
                
            img_path1 = random.choice(self.subject_groups[subject])
            img_path2 = random.choice(self.subject_groups[subject])
            while img_path1 == img_path2:
                img_path2 = random.choice(self.subject_groups[subject])
                
            label = torch.tensor([1.0], dtype=torch.float32)
        else:
            subject1 = random.choice(self.subject_ids)
            subject2 = random.choice(self.subject_ids)
            while subject1 == subject2:
                subject2 = random.choice(self.subject_ids)
                
            img_path1 = random.choice(self.subject_groups[subject1])
            img_path2 = random.choice(self.subject_groups[subject2])
            
            label = torch.tensor([0.0], dtype=torch.float32)

        # 1. Load the images
        img1 = Image.open(img_path1).convert('L')
        img2 = Image.open(img_path2).convert('L')
        
        # 2. TIGHT CORE ISOLATION: Cut away all white paper edges.
        # SOCOFing is usually 96x103. This isolates just the center skin.
        img1 = TF.center_crop(img1, (65, 65))
        img2 = TF.center_crop(img2, (65, 65))
        
        # 3. RIDGE THICKENING: Artificially zoom in to simulate the Egis sensor's DPI.
        # This makes the 3-pixel ridges act like 6-to-8 pixel ridges.
        img1 = TF.resize(img1, (100, 100))
        img2 = TF.resize(img2, (100, 100))
        
        # 4. GENERATE ONE RANDOM CROP BOX FOR BOTH IMAGES
        i, j, h, w = transforms.RandomCrop.get_params(img1, output_size=(57, 70))
        
        # 5. Apply the exact same slice to both images
        img1 = TF.crop(img1, i, j, h, w)
        img2 = TF.crop(img2, i, j, h, w)
        
        # 6. Apply transforms (ToTensor -> SimulateCapacitiveSensor -> ZScoreNormalize)
        img1 = self.transform(img1)
        img2 = self.transform(img2)
        
        return img1, img2, label

def save_debug_images(img_tensor_batch, folder="debug_samples", filename="sample.png"):
    """
    Saves a batch of tensor images to disk as a single image grid.
    """
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    
    # FIX: Tell save_image to mathematically normalize the -3.0 to +3.0 Z-score 
    # back into a 0.0 to 1.0 visual range so it doesn't clamp to pure black/white.
    save_image(img_tensor_batch, filepath, normalize=True, value_range=(-3, 3))
    print(f"[+] Saved visual sample to: {filepath}")

if __name__ == "__main__":
    print("[*] Testing Dataset Factory pipeline...")
    try:
        # Point this to your unzipped folder
        dataset = SiameseFingerprintDataset(root_dir="D:\\GitHub Projects\\EgisTec-EH576\\training_model\\scoofing_data")
        dataloader = DataLoader(dataset, batch_size=4, shuffle=True)
        
        img1_batch, img2_batch, label_batch = next(iter(dataloader))
        print(f"[SUCCESS] Image 1 Batch Shape: {img1_batch.shape}") 
        print(f"[SUCCESS] Image 2 Batch Shape: {img2_batch.shape}") 
        print(f"[SUCCESS] Labels: {label_batch.flatten()}")
        
        # --- NEW CODE: Output images for visual comparison ---
        print("\n[*] Generating visual samples for comparison...")
        save_debug_images(img1_batch, filename="simulated_capacitive_img1.png")
        save_debug_images(img2_batch, filename="simulated_capacitive_img2.png")
        print("[*] Open the 'debug_samples' folder to view the transformed images.")
        
    except Exception as e:
        print(f"[-] Error: {e}")
        
