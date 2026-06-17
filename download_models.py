import os
import urllib.request

def download_file(url, dest_path):
    print(f"Downloading {url} to {dest_path}...")
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        # Setup headers to bypass potential user-agent blocks
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
            data = response.read()
            out_file.write(data)
        print(f"Successfully downloaded {dest_path} ({os.path.getsize(dest_path)} bytes)")
        return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return False

def main():
    # Saafke FSRCNN x2 model
    fsrcnn_url = "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x2.pb"
    fsrcnn_dest = os.path.join("weights", "FSRCNN_x2.pb")
    
    download_file(fsrcnn_url, fsrcnn_dest)
    
    print("\nNote: For YOLO Receipt Detection, you can place your custom-trained YOLOv8/v5 ONNX model ")
    print("at 'weights/yolov8n-document.onnx'. If not present, the pipeline will automatically ")
    print("fall back to the high-performance OpenCV Contour-Based Receipt Cropper.")

if __name__ == "__main__":
    main()
