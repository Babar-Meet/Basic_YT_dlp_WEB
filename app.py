from flask import Flask, render_template, request, jsonify
import yt_dlp
import os
import threading
import time
import uuid

app = Flask(__name__)

# Configuration
DOWNLOAD_PATH = "B:/Downloads/WatchLater"
if not os.path.exists(DOWNLOAD_PATH):
    DOWNLOAD_PATH = os.path.join(os.path.expanduser("~"), "Downloads")

# Store download status
download_status = {}

def get_formats_info(url):
    """Extract available formats from YouTube URL"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get video metadata
            metadata = {
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Unknown'),
                'views': info.get('view_count', 0),
                'duration': info.get('duration', 0),
                'upload_date': info.get('upload_date', ''),
                'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
            }
            
            # Group formats
            formats_by_type = {
                'video_only': [],
                'audio_only': [],
                'video_audio': []
            }
            
            # Process each format
            for fmt in info.get('formats', []):
                format_info = {
                    'format_id': fmt.get('format_id', ''),
                    'ext': fmt.get('ext', ''),
                    'resolution': fmt.get('resolution', ''),
                    'fps': fmt.get('fps', 0),
                    'filesize': fmt.get('filesize', fmt.get('filesize_approx', 0)),
                    'vcodec': fmt.get('vcodec', 'none'),
                    'acodec': fmt.get('acodec', 'none'),
                    'language': fmt.get('language', ''),
                    'format_note': fmt.get('format_note', ''),
                }
                
                # Determine format type
                vcodec = format_info['vcodec'].lower()
                acodec = format_info['acodec'].lower()
                
                # Get codec group
                if 'av01' in vcodec:
                    format_info['codec_group'] = 'av01'
                elif 'vp9' in vcodec:
                    format_info['codec_group'] = 'vp09'
                elif 'avc' in vcodec or 'h264' in vcodec:
                    format_info['codec_group'] = 'h264'
                elif 'hevc' in vcodec or 'h265' in vcodec:
                    format_info['codec_group'] = 'h265'
                elif 'opus' in acodec:
                    format_info['codec_group'] = 'opus'
                elif 'aac' in acodec:
                    format_info['codec_group'] = 'aac'
                elif 'mp3' in acodec:
                    format_info['codec_group'] = 'mp3'
                else:
                    format_info['codec_group'] = 'other'
                
                # Check if original audio
                if 'original' in str(fmt.get('format_note', '')).lower():
                    format_info['is_original'] = True
                else:
                    format_info['is_original'] = False
                
                # Categorize
                if acodec == 'none' and vcodec != 'none':
                    formats_by_type['video_only'].append(format_info)
                elif vcodec == 'none' and acodec != 'none':
                    formats_by_type['audio_only'].append(format_info)
                else:
                    formats_by_type['video_audio'].append(format_info)
            
            return metadata, formats_by_type
            
    except Exception as e:
        return None, str(e)

def download_video(url, format_id, download_id):
    """Download video in background thread"""
    try:
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s.%(ext)s'),
            'progress_hooks': [lambda d: update_progress(d, download_id)],
            'quiet': True,
        }
        
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'filename': '',
            'error': None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Ensure MP4 extension for video+audio downloads
            if format_id not in info.get('format_id', '') and info.get('ext') != 'mp4':
                new_filename = os.path.splitext(filename)[0] + '.mp4'
                if os.path.exists(filename):
                    os.rename(filename, new_filename)
                    filename = new_filename
            
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'filename': filename,
                'title': info.get('title', ''),
                'error': None
            }
            
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'progress': 0,
            'filename': '',
            'error': str(e)
        }

def merge_video_audio(url, video_format_id, audio_format_id, download_id):
    """Merge video and audio formats in background thread"""
    try:
        ydl_opts = {
            'format': f'{video_format_id}+{audio_format_id}',
            'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s.%(ext)s'),
            'progress_hooks': [lambda d: update_progress(d, download_id)],
            'quiet': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        download_status[download_id] = {
            'status': 'downloading',
            'progress': 0,
            'filename': '',
            'error': None
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Ensure MP4 extension
            if not filename.endswith('.mp4'):
                new_filename = os.path.splitext(filename)[0] + '.mp4'
                if os.path.exists(filename):
                    os.rename(filename, new_filename)
                    filename = new_filename
            
            download_status[download_id] = {
                'status': 'completed',
                'progress': 100,
                'filename': filename,
                'title': info.get('title', ''),
                'error': None
            }
            
    except Exception as e:
        download_status[download_id] = {
            'status': 'error',
            'progress': 0,
            'filename': '',
            'error': str(e)
        }

def update_progress(d, download_id):
    """Update download progress"""
    if d['status'] == 'downloading':
        if 'total_bytes' in d:
            progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
        elif 'total_bytes_estimate' in d:
            progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
        else:
            progress = 0
        
        download_status[download_id]['progress'] = round(progress, 2)
        download_status[download_id]['speed'] = d.get('_speed_str', 'N/A')
        download_status[download_id]['eta'] = d.get('_eta_str', 'N/A')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    metadata, formats = get_formats_info(url)
    if isinstance(formats, str):  # Error occurred
        return jsonify({'error': formats}), 400
    
    return jsonify({
        'metadata': metadata,
        'formats': formats
    })

@app.route('/start_download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url or not format_id:
        return jsonify({'error': 'Missing parameters'}), 400
    
    download_id = str(uuid.uuid4())
    
    # Start download in background thread
    thread = threading.Thread(
        target=download_video,
        args=(url, format_id, download_id)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'download_id': download_id})

@app.route('/merge_formats', methods=['POST'])
def merge_formats():
    data = request.json
    url = data.get('url')
    video_format_id = data.get('video_format_id')
    audio_format_id = data.get('audio_format_id')
    
    if not url or not video_format_id or not audio_format_id:
        return jsonify({'error': 'Missing parameters'}), 400
    
    download_id = str(uuid.uuid4())
    
    # Start merge in background thread
    thread = threading.Thread(
        target=merge_video_audio,
        args=(url, video_format_id, audio_format_id, download_id)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'download_id': download_id})

@app.route('/download_status/<download_id>')
def get_download_status(download_id):
    status = download_status.get(download_id, {'status': 'not_found'})
    return jsonify(status)

if __name__ == '__main__':
    app.run(debug=True, port=5000)