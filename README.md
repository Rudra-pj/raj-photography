# 📸 PixelStream-OS - Professional Event Studio Engine

This platform is an enterprise-grade media delivery solution designed for professional event photographers. It bridges the gap between the camera and the client by providing an automated, real-time pipeline for watermarking, uploading, and distributing event media through secure, high-end guest galleries. Built for speed, security, and a premium user experience.

## ✨ Key Features

- **🚀 Live Event Auto-Uploader**: Automatically detects and watermarks photos from your laptop as you shoot.
- **🎨 Professional Watermarking**: Premium aesthetics with 80% opacity and elegant corner placement.
- **🛡️ Duplicate Rejection**: Uses SHA256 hashing to prevent duplicate uploads.
- **♻️ Advanced Recycle Bin**: Secure 30-day "soft-delete" for both media and events.
- **🔒 Secure Admin Dashboard**: Armed with password hashing and recovery keys.
- **📱 Responsive Guest View**: Dynamic galleries with lead generation forms for bookings.

## 🛠️ Tech Stack

- **Frontend/Backend**: [Streamlit](https://streamlit.io/)
- **Database**: SQLite3
- **Image Processing**: Pillow (PIL)
- **Video Processing**: MoviePy (v2.x)
- **QR Codes**: qrcode library

## ⚙️ Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/rudra0133/PixelStream-OS.git
   cd PixelStream-OS
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python -m streamlit run app.py
   ```

## 📝 License
Copyright © 2026 PixelStream-OS. All rights reserved.
