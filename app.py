import streamlit as st
import database as db
import utils
import uuid
import os
import hashlib
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
# import tkinter as tk
# from tkinter import filedialog
import shutil
import pandas as pd

# --- Page Configuration (Must be first Streamlit command) ---
st.set_page_config(page_title="Raj-photography", page_icon="📸", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

def hash_text(text):
    """Simple SHA256 hashing helper."""
    return hashlib.sha256(text.encode()).hexdigest()

def get_file_hash(file_path):
    """Calculates the SHA256 hash of a file's content."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

# Initialize the database
db.init_db()

# --- Sync Logic ---
SYNC_REPORTS = {} # Event ID -> List of logs

def process_single_media(event_id, source_path, watermark_path):
    """Helper to process a single file from local disk to event gallery."""
    try:
        file_ext = os.path.splitext(source_path)[1].lower()
        if file_ext not in [".png", ".jpg", ".jpeg", ".mp4", ".mov", ".avi"]:
            return "invalid_type"
            
        # 1. Check for Duplicate Content
        file_hash = get_file_hash(source_path)
        if db.check_duplicate_media(event_id, file_hash):
            return "duplicate"

        file_type = "video" if file_ext in [".mp4", ".mov", ".avi"] else "image"
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        
        orig_dir = os.path.join("uploads", "originals", event_id)
        wm_dir = os.path.join("uploads", "watermarked", event_id)
        thumb_dir = os.path.join("uploads", "thumbnails", event_id)
        os.makedirs(orig_dir, exist_ok=True)
        os.makedirs(wm_dir, exist_ok=True)
        os.makedirs(thumb_dir, exist_ok=True)

        orig_path = os.path.join(orig_dir, unique_filename)
        wm_path = os.path.join(wm_dir, unique_filename)
        thumb_path = os.path.join(thumb_dir, f"{os.path.splitext(unique_filename)[0]}.jpg")

        import shutil
        shutil.copy2(source_path, orig_path)

        if file_type == "image":
            utils.apply_watermark_to_image(orig_path, watermark_path, wm_path)
            utils.generate_thumbnail(wm_path, thumb_path)
        else:
            utils.apply_watermark_to_video(orig_path, watermark_path, wm_path)
            utils.generate_thumbnail(orig_path, thumb_path) # Video thumb from orig
        
        db.add_media(event_id, file_type, orig_path, wm_path, thumb_path, file_hash)
        return "success"
    except Exception as e:
        print(f"Sync error for {source_path}: {e}")
        return "error"

class FolderSyncHandler(FileSystemEventHandler):
    def __init__(self, event_id, watermark_path):
        self.event_id = event_id
        self.watermark_path = watermark_path
        self.processed_files = set()
        self.in_progress = set()
        import threading
        self.lock = threading.Lock()

    def on_created(self, event):
        if not event.is_directory:
            filename = os.path.basename(event.src_path)
            if filename.startswith('.') or filename.startswith('~'):
                return
            self.process_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.process_file(event.dest_path)

    def process_file(self, file_path):
        filename = os.path.basename(file_path)
        if filename.startswith('.') or filename.startswith('~'):
            return
            
        with self.lock:
            if file_path in self.processed_files or file_path in self.in_progress:
                return
            self.in_progress.add(file_path)

        try:
            status = self.process_with_retry(file_path)
            if status:
                if self.event_id not in SYNC_REPORTS:
                    SYNC_REPORTS[self.event_id] = []
                
                if status == "success":
                    log_msg = f"✅ Auto-Uploaded: {filename} ({time.strftime('%H:%M:%S')})"
                elif status == "duplicate":
                    log_msg = f"⏭️ Skipped (Duplicate): {filename} ({time.strftime('%H:%M:%S')})"
                else:
                    log_msg = f"❌ Error: {filename} ({time.strftime('%H:%M:%S')})"
                
                SYNC_REPORTS[self.event_id].append(log_msg)
                st.cache_data.clear()
                with self.lock:
                    if status in ["success", "duplicate"]:
                        self.processed_files.add(file_path)
        finally:
            with self.lock:
                self.in_progress.discard(file_path)

    def process_with_retry(self, file_path, retries=10):
        """Attempts to process a file multiple times if it's locked or growing."""
        last_size = -1
        for i in range(retries):
            try:
                if not os.path.exists(file_path): return "error"
                
                # 1. Check if file is locked
                with open(file_path, "ab"):
                    pass
                
                # 2. Check if file size is stable (not still being written)
                current_size = os.path.getsize(file_path)
                if current_size == 0:
                    time.sleep(1)
                    continue
                if current_size != last_size:
                    last_size = current_size
                    time.sleep(1)
                    continue

                # If we get here, file is ready and stable
                status = process_single_media(self.event_id, file_path, self.watermark_path)
                return status
            except (IOError, PermissionError):
                time.sleep(1)
        return "error"

# Directory paths
WATERMARK_DIR = "uploads/watermarks"
QRCODE_DIR = "uploads/qrcodes"

def admin_view():
    st.title("Raj-Photography 📸 ")
    
    # Run cleanup of expired items on every dashboard load
    
    # 1. Cleanup Expired Media (30+ days in trash)
    expired_media = db.cleanup_expired_media()
    for mid, opath, wpath, tpath in expired_media:
        try:
            if opath and os.path.exists(opath): os.remove(opath)
            if wpath and os.path.exists(wpath): os.remove(wpath)
            if tpath and os.path.exists(tpath): os.remove(tpath)
            db.delete_media(mid)
        except: pass
        
    # 2. Cleanup Expired Events (30+ days in trash)
    expired_events = db.cleanup_expired_events()
    for eid, ewm, eqr in expired_events:
        try:
            shutil.rmtree(os.path.join("uploads", "originals", eid), ignore_errors=True)
            shutil.rmtree(os.path.join("uploads", "watermarked", eid), ignore_errors=True)
            shutil.rmtree(os.path.join("uploads", "thumbnails", eid), ignore_errors=True)
            db.delete_event(eid)
        except: pass

    # 3. Migrate Missing Thumbnails (Phase 25)
    missing_thumbs = db.get_all_media_for_migration()
    if missing_thumbs:
        with st.status(f"🚀 Optimizing {len(missing_thumbs)} existing files for speed...", expanded=False) as status:
            for mid, eid, ftype, opath, wpath, tpath in missing_thumbs:
                thumb_dir = os.path.join("uploads", "thumbnails", eid)
                os.makedirs(thumb_dir, exist_ok=True)
                # Generate a unique thumb name from original/watermarked filename
                thumb_filename = f"{os.path.basename(opath).split('.')[0]}.jpg"
                new_tpath = os.path.join(thumb_dir, thumb_filename)
                
                # Videos from originals, images from watermarked
                source = wpath if ftype == "image" else opath
                if os.path.exists(source):
                    generated = utils.generate_thumbnail(source, new_tpath)
                    if generated:
                        db.update_media_thumbnail(mid, generated)
            status.update(label="🚀 Speed optimization complete!", state="complete", expanded=False)
            st.cache_data.clear()

    # Cache media fetches for performance
    @st.cache_data(ttl=60)
    def get_cached_media(eid):
        return db.get_event_media(eid)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "🆕 Create Event", 
        "📁 Manage Media", 
        "🖼️ Watermarks", 
        "🗂️ All Events", 
        "♻️ Recycle Bin", 
        "✉️ Leads",
        "⚙️ Settings"
    ])
    
    with tab1:
        st.header("Create New Event")
        with st.form("event_creation_form", clear_on_submit=True):
            event_name = st.text_input("Event Name", placeholder="e.g., Sharma's Wedding 2026")
            
            # Watermark Selection
            st.subheader("Select Watermark")
            existing_wms = db.get_all_watermarks()
            wm_options = ["Upload New"] + [f"{wm[1]} ({wm[3][:10]})" for wm in existing_wms]
            selected_wm_option = st.selectbox("Choose a Watermark", wm_options)
            
            watermark_file = None
            if selected_wm_option == "Upload New":
                watermark_file = st.file_uploader("Upload Master Watermark (PNG recommended)", type=["png", "jpg", "jpeg"])
            else:
                wm_index = wm_options.index(selected_wm_option) - 1
                wm_path = existing_wms[wm_index][2]
                if os.path.exists(wm_path):
                    st.image(wm_path, width=150, caption="Selected Watermark Preview")
                else:
                    st.warning("⚠️ Original watermark file not found on disk.")
            
            submit_button = st.form_submit_button("Create Event")
            
            if submit_button:
                if not event_name:
                    st.error("Please provide an event name.")
                elif selected_wm_option == "Upload New" and not watermark_file:
                    st.error("Please upload a watermark image.")
                else:
                    event_id = str(uuid.uuid4())
                    
                    if selected_wm_option == "Upload New":
                        # Save New Watermark
                        watermark_ext = os.path.splitext(watermark_file.name)[1]
                        watermark_path = os.path.join(WATERMARK_DIR, f"{uuid.uuid4()}{watermark_ext}")
                        os.makedirs(WATERMARK_DIR, exist_ok=True)
                        with open(watermark_path, "wb") as f:
                            f.write(watermark_file.getbuffer())
                        # Save to Watermark Library - Use Original Filename
                        db.add_watermark(watermark_file.name, watermark_path)
                    else:
                        # Use Existing
                        wm_index = wm_options.index(selected_wm_option) - 1
                        watermark_path = existing_wms[wm_index][2]
                    
                    # Generate QR Code
                    local_ip = utils.get_local_ip()
                    detected_url = f"http://{local_ip}:8501"
                    base_url = st.secrets.get("base_url", detected_url)
                    if "localhost" in base_url or "0.0.0.0" in base_url:
                        base_url = detected_url
                    
                    guest_url = f"{base_url}/?event_id={event_id}"
                    qr_path = os.path.join(QRCODE_DIR, f"{event_id}.png")
                    utils.generate_qr_code(guest_url, qr_path)
                    
                    # Save to DB
                    db.create_event(event_id, event_name, watermark_path, qr_path)
                    
                    st.success(f"Event '{event_name}' created successfully!")
                    st.write(f"**Guest URL:** [{guest_url}]({guest_url})")
                    if os.path.exists(qr_path):
                        st.image(os.path.abspath(qr_path), caption="Scan this QR code to access the gallery", width=204)

    with tab2:
        st.header("📁 Manage Event Media")
        events = db.get_all_events()
        if not events:
            st.info("No events found. Create one first!")
        else:
            event_names = {e[1]: e[0] for e in events}
            selected_event_name = st.selectbox("Select Event to Manage", list(event_names.keys()))
            selected_event_id = event_names[selected_event_name]
            
            # Fetch event details
            event_data = db.get_event(selected_event_id)
            watermark_path = event_data[2]
            qr_code_path = event_data[3]
            
            # Show Event Credentials (QR & Link)
            st.divider()
            cred_col1, cred_col2 = st.columns([1, 2])
            with cred_col1:
                if os.path.exists(qr_code_path):
                    st.image(qr_code_path, caption="Event QR Code", width=200)
            with cred_col2:
                local_ip = utils.get_local_ip()
                detected_url = f"http://{local_ip}:8501"
                current_base = st.secrets.get("base_url", detected_url)
                if "localhost" in current_base or "0.0.0.0" in current_base:
                    current_base = detected_url
                guest_url = f"{current_base}/?event_id={selected_event_id}"
                st.subheader("Event Credentials")
                st.write(f"**Event Name:** {selected_event_name}")
                st.write(f"**Event ID:** `{selected_event_id}`")
                st.write(f"**Guest Gallery Link:**")
                st.code(guest_url, language=None)
                st.markdown(f"[Open Gallery ↗️]({guest_url})")

            # --- Live Sync Section ---
            st.divider()
            st.subheader("🔁 Live Folder Sync")
            st.write("Automatically upload photos as they appear in a folder on this laptop.")
            
            sync_active = st.session_state.get('sync_active', False)
            sync_enabled = st.toggle("Enable Live Auto-Upload", value=sync_active)
            
            if sync_enabled:
                col1, col2 = st.columns([3, 1])
                with col1:
                    sync_folder = st.text_input("Local Folder Path to Watch", 
                                               value=st.session_state.get('sync_folder', ""), 
                                               placeholder="Enter folder path manually...",
                                               help="Paste the full path to the folder where your photos land.")
                with col2:
                    st.write("") # Padding
                    st.write("") # Padding
                    os.makedirs("uploads", exist_ok=True)
                    
                    uploaded_files = st.file_uploader(
                        "Upload Images",
                        accept_multiple_files=True
                    )
                    
                    if uploaded_files:
                        for file in uploaded_files:
                            file_path = os.path.join("uploads", file.name)
                            with open(file_path, "wb") as f:
                                f.write(file.getbuffer())
                        st.success("Files uploaded successfully!")

                if sync_folder:
                    if not os.path.isdir(sync_folder):
                        st.error("⚠️ Invalid folder path. Please check if it exists.")
                    else:
                        if not st.session_state.get('sync_active'):
                            # Start Background Watcher
                            SYNC_REPORTS[selected_event_id] = ["🚀 Sync Started: Watching folder..."]
                            handler = FolderSyncHandler(selected_event_id, watermark_path)
                            
                            # PHASE 26: Initial Scan for existing files
                            existing_files = [f for f in os.listdir(sync_folder) 
                                             if os.path.isfile(os.path.join(sync_folder, f)) 
                                             and not f.startswith('.') and not f.startswith('~')]
                            
                            if existing_files:
                                SYNC_REPORTS[selected_event_id].append(f"🔍 Found {len(existing_files)} existing files. Processing...")
                                for f in existing_files:
                                    full_path = os.path.join(sync_folder, f)
                                    status = handler.process_with_retry(full_path)
                                    if status == "success":
                                        handler.processed_files.add(full_path)
                                        SYNC_REPORTS[selected_event_id].append(f"✅ Found & Uploaded: {f}")
                                    elif status == "duplicate":
                                        handler.processed_files.add(full_path)
                                        SYNC_REPORTS[selected_event_id].append(f"⏭️ Existing (Duplicate): {f}")
                                    else:
                                        SYNC_REPORTS[selected_event_id].append(f"❌ Error on existing: {f}")
                            
                            observer = Observer()
                            observer.schedule(handler, sync_folder, recursive=False)
                            observer.start()
                            
                            st.session_state.observer = observer
                            st.session_state.sync_active = True
                            st.session_state.sync_event_id = selected_event_id
                            st.session_state.sync_folder = sync_folder
                            st.rerun()
                        
                        if st.session_state.get('sync_event_id') != selected_event_id:
                             st.warning("⚠️ Sync is active for a different event. Stop it first to switch.")
                        else:
                             st.success(f"✅ Active Sync: `{sync_folder}`")
                             st.info("💡 Synchronizing... New photos will appear in the gallery automatically.")
                        
                        # Display Logs from Global Queue
                        with st.container(height=180, border=True):
                            st.caption("Auto-Uploader Activity")
                            logs = SYNC_REPORTS.get(selected_event_id, [])
                            if logs:
                                for log in reversed(logs):
                                    st.write(log)
                            else:
                                st.write("Waiting for files...")
                        
                        # Trigger autorefresh to show new logs
                        st_autorefresh(interval=3000, key="sync_refresh")
                else:
                    st.warning("Enter a local folder path to begin synchronization.")
            else:
                if st.session_state.get('sync_active'):
                    # Stop the watcher
                    if 'observer' in st.session_state:
                        try:
                            st.session_state.observer.stop()
                            st.session_state.observer.join()
                        except: pass
                        del st.session_state.observer
                    st.session_state.sync_active = False
                    st.session_state.sync_logs = []
                    st.info("Sync stopped.")
                    st.rerun()

            st.divider()
            st.subheader(f"Upload Photos/Videos for: {selected_event_name}")
            uploaded_files = st.file_uploader(
                "Select one or more photos/videos to watermark and upload",
                type=["png", "jpg", "jpeg", "mp4", "mov", "avi"],
                accept_multiple_files=True
            )
            
            if uploaded_files:
                if st.button(f"Process and Upload {len(uploaded_files)} Files"):
                    progress_text = "Processing media... Please wait."
                    my_bar = st.progress(0, text=progress_text)
                    orig_dir = os.path.join("uploads", "originals", selected_event_id)
                    wm_dir = os.path.join("uploads", "watermarked", selected_event_id)
                    thumb_dir = os.path.join("uploads", "thumbnails", selected_event_id)
                    os.makedirs(orig_dir, exist_ok=True)
                    os.makedirs(wm_dir, exist_ok=True)
                    os.makedirs(thumb_dir, exist_ok=True)
                    success_count = 0
                    duplicate_count = 0
                    duplicate_names = []
                    for i, file in enumerate(uploaded_files):
                        try:
                            # 1. Hashing for duplicate detection
                            file_bytes = file.getvalue()
                            file_hash = hashlib.sha256(file_bytes).hexdigest()
                            
                            if db.check_duplicate_media(selected_event_id, file_hash):
                                duplicate_count += 1
                                duplicate_names.append(file.name)
                                continue

                            file_ext = os.path.splitext(file.name)[1].lower()
                            file_type = "video" if file_ext in [".mp4", ".mov", ".avi"] else "image"
                            unique_filename = f"{uuid.uuid4()}{file_ext}"
                            orig_path = os.path.join(orig_dir, unique_filename)
                            wm_path = os.path.join(wm_dir, unique_filename)
                            thumb_path = os.path.join(thumb_dir, f"{os.path.splitext(unique_filename)[0]}.jpg")
                            
                            with open(orig_path, "wb") as f:
                                f.write(file_bytes)
                            if file_type == "image":
                                utils.apply_watermark_to_image(orig_path, watermark_path, wm_path)
                                utils.generate_thumbnail(wm_path, thumb_path)
                            else:
                                utils.apply_watermark_to_video(orig_path, watermark_path, wm_path)
                                utils.generate_thumbnail(orig_path, thumb_path)
                            db.add_media(selected_event_id, file_type, orig_path, wm_path, thumb_path, file_hash)
                            success_count += 1
                        except Exception as e:
                            st.error(f"Error processing {file.name}: {e}")
                        progress = (i + 1) / len(uploaded_files)
                        my_bar.progress(progress, text=f"Processed {i+1}/{len(uploaded_files)} files")
                    
                    if success_count > 0:
                        st.success(f"Successfully processed and uploaded {success_count} files!")
                    if duplicate_count > 0:
                        st.warning(f"Skipped {duplicate_count} duplicate files: {', '.join(duplicate_names)}")
                        st.info("💡 If you want to re-upload these, please move the old ones to the Recycle Bin or delete them permanently first.")
            
            st.divider()
            with st.expander("🛠️ Phone Connectivity Troubleshooting"):
                st.write("If your phone says **'Site can't be reached'**, check these 3 things:")
                st.markdown(f"""
                1. **WiFi**: Both your computer and phone must be on the **same WiFi network**.
                2. **Firewall**: Your Windows Firewall might be blocking the connection. 
                   * Search for 'Allow an app through Windows Firewall' in your Start menu.
                   * Find **'python'** or **'Streamlit'** and make sure 'Private' and 'Public' are checked.
                3. **IP Address**: Ensure your computer's IP hasn't changed.
                """)
                st.info(f"Your computer's detected Network IP: **{utils.get_local_ip()}**")
                st.write("Try running the app with this command to force network access:")
                st.code(f"python -m streamlit run app.py --server.address 0.0.0.0")
            
            st.divider()
            
            # Event Action Header
            m_col1, m_col2 = st.columns([3, 1])
            with m_col1:
                st.subheader(f"🖼️ Media for: {next(e[1] for e in events if e[0] == selected_event_id)}")
            with m_col2:
                if st.button("♻️ Trash Event", help="Move this entire event to Recycle Bin"):
                    db.soft_delete_event(selected_event_id)
                    st.success("Event moved to Recycle Bin.")
                    st.cache_data.clear() # Clear cache on structural change
                    st.rerun()

            media_items = get_cached_media(selected_event_id)
            if not media_items:
                st.info("No media uploaded for this event yet.")
            else:
                st.write(f"📊 **Total Media:** {len(media_items)} items")
                # Bulk Media Selection
                selected_media_ids = []
                
                # Filter/Sort options could go here
                
                cols = st.columns(3)
                for idx, item in enumerate(media_items):
                    # media_id, event_id, file_type, orig_path, wm_path, uploaded_at, is_deleted, deleted_at, file_hash, thumbnail_path
                    media_id, _, file_type, orig_path, wm_path, uploaded_at, is_del, d_at, f_hash, *rest = item
                    thumbnail_path = rest[0] if rest else None
                    display_path = thumbnail_path if thumbnail_path and os.path.exists(thumbnail_path) else wm_path

                    with cols[idx % 3]:
                        st.markdown('<div style="background: rgba(255,255,255,0.05); padding: 10px; border-radius: 10px; margin-bottom: 10px;">', unsafe_allow_html=True)
                        if os.path.exists(display_path):
                            try:
                                if file_type == "image":
                                    st.image(os.path.abspath(display_path), use_column_width=True)
                                else:
                                    if os.path.exists(wm_path): st.video(os.path.abspath(wm_path))
                                    else: st.warning("Video missing")
                            except Exception as e:
                                st.error(f"⚠️ Render Error: {e}")
                        else:
                            st.error("⚠️ File Missing")
                            if st.button("🗑️ Remove Entry", key=f"fix_m_{media_id}"):
                                db.delete_media(media_id)
                                st.cache_data.clear()
                                st.rerun()
                        
                        st.caption(f"📅 {uploaded_at[:16]}")
                        
                        # Selection and Individual Delete
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.checkbox("Select", key=f"sel_med_{media_id}"):
                                selected_media_ids.append((media_id, orig_path, wm_path))
                        with c2:
                            if st.button(f"🗑️ Trash", key=f"del_{media_id}"):
                                db.soft_delete_media(media_id)
                                st.success("Moved to Trash!")
                                st.cache_data.clear()
                                st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)

                if selected_media_ids:
                    st.divider()
                    if st.button(f"♻️ Move {len(selected_media_ids)} Selected Files to Trash", type="secondary"):
                        for mid, _, _ in selected_media_ids:
                            db.soft_delete_media(mid)
                        st.success(f"{len(selected_media_ids)} files moved to trash.")
                        st.cache_data.clear()
                        st.rerun()

    with tab3:
        st.header("🖼️ Watermark Library")
        st.write("Manage your saved watermarks for future reuse.")
        
        # Check for watermark zoom
        if "wm_modal" not in st.session_state:
            st.session_state.wm_modal = None
            
        if st.session_state.wm_modal:
            st.markdown('<div style="background:rgba(0,0,0,0.9); padding:20px; border-radius:15px; margin-bottom:20px;">', unsafe_allow_html=True)
            if st.button("❌ Close Preview", use_container_width=True):
                st.session_state.wm_modal = None
                st.rerun()
            if os.path.exists(st.session_state.wm_modal):
                st.image(st.session_state.wm_modal, use_column_width=True)
            else:
                st.error("Preview file missing.")
            st.markdown('</div>', unsafe_allow_html=True)
        
        wms = db.get_all_watermarks()
        if not wms:
            st.info("No watermarks saved yet. They are saved automatically when you create an event.")
        else:
            cols = st.columns(4)
            for idx, wm in enumerate(wms):
                wid, wname, wpath, wcat = wm
                with cols[idx % 4]:
                    with st.container(border=True):
                        if os.path.exists(wpath):
                            st.image(wpath, use_column_width=True)
                        else:
                            st.warning("File Missing")
                        
                        st.write(f"**{wname}**")
                        
                        vcol, dcol = st.columns(2)
                        with vcol:
                            if st.button("🔍 View", key=f"view_wm_{wid}", use_container_width=True):
                                st.session_state.wm_modal = wpath
                                st.rerun()
                        with dcol:
                            if st.button("🗑️ Del", key=f"del_wm_{wid}", use_container_width=True):
                                if os.path.exists(wpath):
                                    try: os.remove(wpath)
                                    except: pass
                                db.delete_watermark(wid)
                                st.success("Deleted")
                                st.rerun()

    with tab4:
        st.header("🗂️ Event Directory")
        all_events = db.get_all_events()
        
        # Search and Filter
        search_col1, search_col2 = st.columns([2, 1])
        with search_col1:
            search_query = st.text_input("🔍 Search Active Events", placeholder="Name or Date...")
        with search_col2:
            st.write("") # Spacer
            if st.button("🔄 Refresh"): st.rerun()

        # Filtering logic
        filtered_events = [e for e in all_events if not search_query or search_query.lower() in e[1].lower() or search_query in e[4]]

        if not filtered_events:
            st.info("No active events found.")
        else:
            selected_ids = []
            st.write(f"Showing {len(filtered_events)} active events.")
            
            for event in filtered_events:
                eid, ename, ewm, eqr, ecat, *rest = event
                with st.expander(f"📅 {ecat[:10]} | 🏷️ {ename}"):
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        if eqr and os.path.exists(eqr):
                            st.image(eqr, width=200)
                        else:
                            st.warning("QR Code missing. Re-create event if needed.")
                        if st.checkbox("Select for bulk action", key=f"sel_act_{eid}"):
                            selected_ids.append(eid)
                    with col2:
                        st.write(f"**Event ID:** `{eid}`")
                        st.write(f"**Created At:** {ecat}")
                        
                        event_status = event[7] if len(event) > 7 else "Active"
                        st.write(f"**Status:** {'🟢 Active' if event_status == 'Active' else '🔴 Ended'}")
                        
                        b1, b2, b3 = st.columns(3)
                        with b1:
                            if event_status == "Active":
                                if st.button(f"🚫 End Event", key=f"end_{eid}"):
                                    db.set_event_status(eid, "Ended")
                                    st.warning(f"'{ename}' has been ended.")
                                    st.rerun()
                            else:
                                if st.button(f"🟢 Re-open Event", key=f"reopen_{eid}"):
                                    db.set_event_status(eid, "Active")
                                    st.success(f"'{ename}' has been re-opened.")
                                    st.rerun()
                        with b2:
                            if st.button(f"♻️ Move to Trash", key=f"mv_trash_{eid}"):
                                db.soft_delete_event(eid)
                                st.success(f"'{ename}' moved to Recycle Bin.")
                                st.rerun()

            if selected_ids:
                if st.button(f"🗑️ Move {len(selected_ids)} to Recycle Bin", type="secondary"):
                    for sid in selected_ids:
                        db.soft_delete_event(sid)
                    st.success("Selected events moved to Recycle Bin.")
                    st.rerun()

    with tab5:
        st.header("♻️ Recycle Bin")
        st.caption("Items are kept here for 30 days before permanent deletion.")
        
        m_trash_tab, e_trash_tab = st.tabs(["🖼️ Deleted Media", "📁 Deleted Events"])
        
        with m_trash_tab:
            deleted_media = db.get_deleted_media()
            if not deleted_media:
                st.info("No media in trash.")
            else:
                # Selection Controls
                sel_col1, sel_col2 = st.columns([1, 1])
                with sel_col1:
                    select_all = st.checkbox("✅ Select All for Burning", key="sel_all_trash")
                
                selected_burn_ids = []
                
                cols = st.columns(3)
                for idx, m in enumerate(deleted_media):
                    # media_id, event_id, ftype, opath, wpath, uat, is_deleted, deleted_at, file_hash, thumbnail_path
                    mid, eid, ftype, opath, wpath, uat, is_deleted, deleted_at, f_hash, *rest = m
                    thumbnail_path = rest[0] if rest else None
                    with cols[idx % 3]:
                        st.markdown('<div style="background: rgba(255,255,255,0.05); padding: 5px; border-radius: 10px; margin-bottom: 5px;">', unsafe_allow_html=True)
                        if os.path.exists(wpath):
                            try:
                                if ftype == "image": st.image(os.path.abspath(wpath), use_column_width=True)
                                else: st.video(os.path.abspath(wpath))
                            except Exception as e:
                                st.error(f"⚠️ Trash Render Error: {e}")
                        else:
                            st.error("⚠️ File missing")
                            if st.button("🗑️ Clear Record", key=f"clr_m_{mid}"):
                                db.delete_media(mid)
                                st.rerun()
                        st.caption(f"Trashed: {deleted_at[:16]}")
                        
                        tr1, tr2 = st.columns(2)
                        with tr1:
                            if st.checkbox("Select", key=f"sel_burn_{mid}", value=select_all):
                                selected_burn_ids.append((mid, opath, wpath, thumbnail_path))
                        with tr2:
                            if st.button("✅ Restore", key=f"rest_med_{mid}"):
                                db.restore_media(mid)
                                st.success("Restored!")
                                st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                
                if selected_burn_ids:
                    st.divider()
                    if st.button(f"🔥 Burn {len(selected_burn_ids)} Selected Files Permanently", type="secondary", use_container_width=True):
                        for b_mid, b_opath, b_wpath, b_tpath in selected_burn_ids:
                            try:
                                if b_opath and os.path.exists(b_opath): os.remove(b_opath)
                                if b_wpath and os.path.exists(b_wpath): os.remove(b_wpath)
                                if b_tpath and os.path.exists(b_tpath): os.remove(b_tpath)
                            except: pass
                            db.delete_media(b_mid)
                        st.success(f"Successfully burned {len(selected_burn_ids)} files!")
                        st.rerun()

        with e_trash_tab:
            deleted_events = db.get_deleted_events()
            if not deleted_events:
                st.info("The Recycle Bin is empty.")
            else:
                for event in deleted_events:
                    eid, ename, ewm, eqr, ecat, is_del, dcat, estatus = event
                    with st.expander(f"🗑️ Deleted: {dcat[:10]} | 🏷️ {ename}"):
                        st.write(f"**Original Creation:** {ecat}")
                        st.write(f"**Deleted On:** {dcat}")
                        
                        rcol1, rcol2 = st.columns(2)
                        with rcol1:
                            if st.button(f"✅ Restore Event", key=f"restore_{eid}"):
                                db.restore_event(eid)
                                st.success(f"'{ename}' restored.")
                                st.rerun()
                        with rcol2:
                            if st.button(f"🔥 Delete Permanently", key=f"perm_del_{eid}"):
                                # Cleanup files and directories
                                try:
                                    # Use shutil.rmtree for a clean sweep of all event-linked folders
                                    shutil.rmtree(os.path.abspath(os.path.join("uploads", "originals", eid)), ignore_errors=True)
                                    shutil.rmtree(os.path.abspath(os.path.join("uploads", "watermarked", eid)), ignore_errors=True)
                                    shutil.rmtree(os.path.abspath(os.path.join("uploads", "thumbnails", eid)), ignore_errors=True)
                                    if eqr and os.path.exists(eqr): os.remove(eqr)
                                    if ewm and os.path.exists(ewm): os.remove(ewm)
                                except: pass
                                db.delete_event(eid)
                                st.success(f"'{ename}' and all its media purged.")
                                st.rerun()

    with tab6:
        st.header("✉️ Leads Management")
        leads = db.get_all_leads()
        if not leads:
            st.info("No leads captured yet.")
        else:
            df = pd.DataFrame(leads, columns=["ID", "Name", "Contact", "Event Type", "Captured At"])
            st.dataframe(df, use_container_width=True)

    with tab7:
        st.header("⚙️ System Settings & Maintenance")
        
        st.subheader("🧹 Deep Storage Cleanup")
        st.write("Scan and remove orphaned thumbnails/watermarks that are no longer linked to any event in the database.")
        
        if st.button("🚀 Start Deep Cleanup Scan", type="primary", use_container_width=True):
            with st.status("🔍 Scanning for orphaned files...", expanded=True) as status:
                # 1. Get all active files from DB to protect them
                conn = db.get_connection()
                all_media = conn.execute("SELECT original_file_path, watermarked_file_path, thumbnail_path FROM media").fetchall()
                all_events = conn.execute("SELECT watermark_path, qr_code_path FROM events").fetchall()
                conn.close()
                
                known_paths = set()
                for row in all_media:
                    for p in row: 
                        if p: known_paths.add(os.path.abspath(p).lower())
                for row in all_events:
                    for p in row: 
                        if p: known_paths.add(os.path.abspath(p).lower())
                
                # 2. Scan directories for orphans (Files & Folders)
                removed_count = 0
                scan_dirs = ["uploads/thumbnails", "uploads/watermarked", "uploads/originals", "uploads/watermarks", "uploads/qrcodes"]
                
                # Get active event IDs to protect their folders
                conn = db.get_connection()
                active_event_ids = {row[0] for row in conn.execute("SELECT event_id FROM events").fetchall()}
                conn.close()

                for sdir in scan_dirs:
                    abs_sdir = os.path.abspath(sdir)
                    if not os.path.exists(abs_sdir): continue
                    
                    # A. Clear Orphaned Files
                    for root, dirs, files in os.walk(abs_sdir, topdown=False):
                        for f in files:
                            fpath = os.path.abspath(os.path.join(root, f))
                            if fpath.lower() not in known_paths:
                                try:
                                    os.remove(fpath)
                                    removed_count += 1
                                    st.write(f"🗑️ Deleted orphan file: {f}")
                                except: pass
                        
                        # B. Clear Orphaned/Empty Subdirectories (Event Folders)
                        for d in dirs:
                            dpath = os.path.abspath(os.path.join(root, d))
                            # If it's a UUID-named folder (event folder), check if event exists
                            is_uuid = False
                            try:
                                uuid.UUID(d)
                                is_uuid = True
                            except: pass

                            if is_uuid and d not in active_event_ids:
                                try:
                                    shutil.rmtree(dpath)
                                    removed_count += 1
                                    st.write(f"🧹 Purged orphaned event folder: {d}")
                                except: pass
                            elif not os.listdir(dpath): # Delete any empty folders
                                try:
                                    os.rmdir(dpath)
                                except: pass
                
                status.update(label=f"✅ Deep Cleanup complete! Purged {removed_count} orphaned items.", state="complete")
        
        st.caption("© 2026 PixelStream-OS | Enterprise Security v26.1")

from streamlit_autorefresh import st_autorefresh

def guest_view(event_id):
    # Auto-refresh every 15 seconds
    st_autorefresh(interval=15000, key="gallery_refresh")
    
    event = db.get_event(event_id)
    if not event:
        st.error("Event not found. Please check the QR code or link.")
        if st.button("Go to Admin Login"):
            st.query_params.clear()
            st.rerun()
        return

    # Check Event Status
    event_status = event[7] if len(event) > 7 else "Active"
    if event_status == "Ended":
        st.markdown(f"""
            <div style="text-align: center; padding: 50px; background: rgba(255, 0, 0, 0.1); border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.2); backdrop-filter: blur(10px);">
                <h1 style="color: #ff4b4b;">🔒 Event Closed</h1>
                <p style="font-size: 1.2rem; margin-bottom: 20px;">The gallery for <b>{event[1]}</b> is currently unavailable because the event has ended.</p>
                <p>Please contact PixelStream-OS for further assistance.</p>
            </div>
        """, unsafe_allow_html=True)
        if st.button("Go to Admin Login"):
            st.query_params.clear()
            st.rerun()
        return

    st.markdown(f"""
        <style>
        .main {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
        }}
        .stButton>button {{
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: white;
            transition: all 0.3s ease;
        }}
        .stButton>button:hover {{
            background: rgba(255, 255, 255, 0.2);
            transform: scale(1.05);
        }}
        .gallery-card {{
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(15px);
            border-radius: 15px;
            padding: 10px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            margin-bottom: 20px;
        }}
        img {{
            border-radius: 10px;
            max-width: 100%;
            height: auto;
            touch-action: manipulation;
        }}
        .stDownloadButton>button {{
            width: 100%;
        }}
        </style>
    """, unsafe_allow_html=True)

    st.title(f"📸 {event[1]}")
    st.write("---")

    # Cache media fetches for performance
    @st.cache_data(ttl=30)
    def get_guest_media(eid):
        return db.get_event_media(eid)
        
    media_items = get_guest_media(event_id)
    
    if not media_items:
        st.info("The gallery is empty. Photos will appear here as they are uploaded!")
    else:
        st.write(f"🖼️ **Total Photos:** {len(media_items)}")
        # Gallery Grid
        cols = st.columns(2) 
        for idx, item in enumerate(media_items):
            # media_id, event_id, file_type, orig_path, wm_path, uploaded_at, is_deleted, deleted_at, file_hash, thumbnail_path
            media_id, _, file_type, orig_path, wm_path, uploaded_at, is_del, d_at, f_hash, *rest = item
            thumbnail_path = rest[0] if rest else None
            display_path = thumbnail_path if thumbnail_path and os.path.exists(thumbnail_path) else wm_path

            with cols[idx % 2]:
                st.markdown('<div class="gallery-card">', unsafe_allow_html=True)
                
                if os.path.exists(display_path):
                    try:
                        if file_type == "image":
                            st.image(os.path.abspath(display_path), use_column_width=True)
                        else:
                            if os.path.exists(wm_path): st.video(os.path.abspath(wm_path))
                            else: st.info("Video pending...")
                    except:
                        st.info("⌛ Loading media...")
                else:
                    st.info("⌛ Image loading...")
                
                # Download button
                if os.path.exists(wm_path):
                    with open(wm_path, "rb") as file:
                        st.download_button(
                            label="📥 Download",
                            data=file,
                            file_name=os.path.basename(wm_path),
                            mime="image/jpeg" if file_type == "image" else "video/mp4",
                            key=f"dl_{idx}"
                        )
                else:
                    st.info("⌛ Preparing high-res...")
                st.markdown('</div>', unsafe_allow_html=True)

    # Sidebar Lead Generation Form
    with st.sidebar:
        st.title("✨ Contact PixelStream-OS")
        st.write("Planning an event? Get in touch with us!")
        
        with st.form("lead_form", clear_on_submit=True):
            name = st.text_input("Name", placeholder="Your Name")
            contact = st.text_input("WhatsApp / Email", placeholder="How can we reach you?")
            event_type = st.selectbox("Event Type", ["Wedding", "Engagement", "Pre-Wedding", "Birthday", "Other"])
            
            submit_lead = st.form_submit_button("Submit Request")
            
            if submit_lead:
                if not name or not contact:
                    st.error("Please provide both name and contact info.")
                else:
                    db.add_lead(name, contact, event_type)
                    st.balloons()
                    st.success(f"Thank you, {name}! We'll contact you soon.")
        
        st.divider()
        st.caption("© 2026 PixelStream-OS. All rights reserved.")

def main():
    # Use streamlit query parameters for routing
    query_params = st.query_params
    
    if "event_id" in query_params:
        event_id = query_params["event_id"]
        guest_view(event_id)
        return

    # Admin Authentication Logic
    if "authenticated" not in st.session_state:
        # Check if persistent session exists in URL
        if query_params.get("admsid") == hash_text(st.secrets.get("recovery_key", "pro_session")):
            st.session_state.authenticated = True
        else:
            st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.markdown(f"""
            <style>
            @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');
            
            /* Force hide scrollbars */
            .stApp {{
                background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
                background-attachment: fixed;
                font-family: 'Outfit', sans-serif;
                overflow: hidden !important;
            }}
            
            header {{visibility: hidden;}}
            footer {{visibility: hidden;}}
            
            /* Absolute centering to bypass Streamlit padding */
            .main-container {{
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 100%;
                display: flex;
                flex-direction: column;
                align-items: center;
                z-index: 9999;
            }}
            
            .auth-card {{
                background: none !important;
                backdrop-filter: none !important;
                border: none !important;
                padding: 1rem;
                max-width: 320px;
                width: 90%;
                text-align: center;
                animation: fadeIn 0.4s ease-out;
            }}
            
            @keyframes fadeIn {{
                from {{ opacity: 0; }}
                to {{ opacity: 1; }}
            }}
            
            .auth-logo {{ font-size: 2rem; margin-bottom: 5px; display: block; }}
            .auth-title {{ color: white; font-weight: 600; font-size: 1.8rem; margin-bottom: 2px; }}
            .auth-subtitle {{ color: rgba(255, 255, 255, 0.5); font-size: 0.85rem; margin-bottom: 1.5rem; }}
            
            /* Borderless UI */
            [data-testid="stForm"], [data-testid="stForm"] > div {{
                border: none !important;
                padding: 0 !important;
                margin: 0 !important;
                box-shadow: none !important;
            }}
            
            [data-testid="stWidgetLabel"] {{
                display: none !important;
            }}
            
            .stTextInput {{
                margin-bottom: 10px !important;
            }}
            
            .stTextInput>div>div>input {{
                background: none !important;
                border: none !important;
                border-bottom: 1px solid rgba(255, 255, 255, 0.2) !important;
                border-radius: 0 !important;
                height: 42px !important;
                color: white !important;
                box-shadow: none !important;
                padding: 0 5px !important;
            }}
            
            .stTextInput>div>div>input:focus {{
                border-bottom: 1px solid white !important;
                background: rgba(255, 255, 255, 0.1) !important;
            }}
            
            .stButton {{
                margin-top: 5px !important;
            }}
            
            .stButton>button {{
                border: 1px solid rgba(255, 255, 255, 0.3) !important;
                background: none !important;
                border-radius: 4px !important;
                font-weight: 600 !important;
                height: 42px !important;
                color: white !important;
                transition: 0.3s all;
            }}
            
            .stButton>button:hover {{
                border-color: white !important;
                background: rgba(255, 255, 255, 0.1) !important;
            }}

            /* Minimal Text Buttons (Forgot Password / Back) */
            div[data-testid="column"] button, .stButton>button[kind="secondary"] {{
                border: none !important;
                background: none !important;
                color: rgba(255, 255, 255, 0.5) !important;
                font-size: 0.8rem !important;
                height: auto !important;
                margin-top: 10px !important;
                text-decoration: underline !important;
            }}
            
            div[data-testid="column"] button:hover, .stButton>button[kind="secondary"]:hover {{
                color: white !important;
            }}

            .reset-link {{
                color: rgba(255, 255, 255, 0.4);
                font-size: 0.8rem;
                text-decoration: underline;
                cursor: pointer;
                transition: 0.2s;
                margin-top: 15px;
                display: inline-block;
            }}
            .reset-link:hover {{ color: white; }}
            </style>
        """, unsafe_allow_html=True)

        admin_data = db.get_admin_auth()
        
        # Initialize sub-mode for recovery if not set
        if "auth_mode" not in st.session_state:
            st.session_state.auth_mode = "login"

        if not admin_data:
            # First time setup
            st.markdown('<div class="main-container"><div class="auth-card">', unsafe_allow_html=True)
            st.markdown('<span class="auth-logo">📸</span>', unsafe_allow_html=True)
            st.markdown('<h1 class="auth-title">ADMIN Login</h1>', unsafe_allow_html=True)
            st.markdown('<p class="auth-subtitle">Setup your secure credentials</p>', unsafe_allow_html=True)
            
            with st.form("setup_form"):
                new_pwd = st.text_input("Password", type="password", placeholder="New Password", label_visibility="collapsed")
                confirm_pwd = st.text_input("Confirm", type="password", placeholder="Confirm Password", label_visibility="collapsed")
                recovery_key = st.text_input("Key", type="password", placeholder="Recovery Key", label_visibility="collapsed")
                setup_submit = st.form_submit_button("Launch Dashboard", use_container_width=True)
                
                if setup_submit:
                    if len(new_pwd) < 6: st.error("Min 6 chars.")
                    elif new_pwd != confirm_pwd: st.error("Mismatch.")
                    elif not recovery_key: st.error("Key req.")
                    else:
                        db.save_admin_auth(hash_text(new_pwd), hash_text(recovery_key))
                        st.rerun()
            st.markdown('</div></div>', unsafe_allow_html=True)
        else:
            # Main Login Dashboard
            st.markdown('<div class="main-container"><div class="auth-card">', unsafe_allow_html=True)
            st.markdown('<h1 class="auth-title">ADMIN Login</h1>', unsafe_allow_html=True)
            
            if st.session_state.auth_mode == "login":
                with st.form("login_form"):
                    pwd_input = st.text_input("Password", type="password", placeholder="••••••••", label_visibility="collapsed")
                    login_submit = st.form_submit_button("Enter Dashboard", use_container_width=True)
                    
                    if login_submit:
                        stored_pwd_hash, _ = admin_data
                        if hash_text(pwd_input) == stored_pwd_hash:
                            st.session_state.authenticated = True
                            # Set persistent session in URL
                            st.query_params["admsid"] = hash_text(st.secrets.get("recovery_key", "pro_session"))
                            st.rerun()
                        else:
                            st.error("Incorrect password.")
                
                if st.button("Forgot Password?", key="forgot_btn"):
                    st.session_state.auth_mode = "reset"
                    st.rerun()
            else:
                st.markdown('<p class="auth-subtitle">Password Reset</p>', unsafe_allow_html=True)
                with st.form("recovery_form"):
                    rec_input = st.text_input("Key", type="password", placeholder="Recovery Key", label_visibility="collapsed")
                    new_pwd = st.text_input("New Pwd", type="password", placeholder="New Password", label_visibility="collapsed")
                    rec_submit = st.form_submit_button("Reset & Login", use_container_width=True)
                    
                    if rec_submit:
                        _, stored_rec_hash = admin_data
                        if hash_text(rec_input) == stored_rec_hash:
                            if len(new_pwd) < 6: st.error("Min 6 chars.")
                            else:
                                db.update_admin_password(hash_text(new_pwd))
                                st.session_state.auth_mode = "login"
                                st.rerun()
                        else: st.error("Invalid Key.")
                
                if st.button("Cancel & Back", key="back_btn"):
                    st.session_state.auth_mode = "login"
                    st.rerun()
            
            st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        # Show a logout button in the sidebar
        with st.sidebar:
            if st.button("🚪 Logout Admin"):
                st.session_state.authenticated = False
                st.query_params.clear()
                st.rerun()
        admin_view()

if __name__ == "__main__":
    main()


