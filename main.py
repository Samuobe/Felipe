import os
import shutil
import subprocess
import threading
import time
import zipfile
from flask import Flask, request, redirect, url_for, render_template, send_file, session, flash, send_from_directory
from werkzeug.utils import secure_filename
import yt_dlp 

app = Flask(__name__)
app.secret_key = 'super_secret_session_key_for_separate_music' # Necessario per usare session

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"
USERS_FILE = "users.txt"
ALLOWED_EXTENSIONS = {'mp3', 'wav'}

tasks_status = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_dir(base_folder, username):
    user_folder = os.path.join(base_folder, username)
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_unique_folder(base_dir, base_name):
    folder_path = os.path.join(base_dir, base_name)
    counter = 1
    while os.path.exists(folder_path) or os.path.exists(folder_path + ".zip"):
        folder_path = os.path.join(base_dir, f"{base_name}_{counter}")
        counter += 1
    return folder_path

# --- LOGIN E REGISTRAZIONE ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with open(USERS_FILE, 'a') as f:
            f.write(f"{username},{password}\n")
        flash('Registrazione completata, effettua il login.')
        return redirect(url_for('login'))
    return render_template("register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r') as f:
                for line in f:
                    u, p = line.strip().split(',')
                    if u == username and p == password:
                        session['username'] = username
                        return redirect(url_for('index'))
        flash('Credenziali non valide.')
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# --- INDEX E CARICAMENTO ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    user_upload_dir = get_user_dir(UPLOAD_FOLDER, username)
    user_output_dir = get_user_dir(OUTPUT_FOLDER, username)

    if request.method == 'POST':
               # 1. Caso A: L'utente ha incollato un link di YouTube
        youtube_url = request.form.get('youtube_url')
        if youtube_url and youtube_url.strip():
            try:
                # Impostazioni per scaricare l'audio e aggirare i blocchi 403
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'outtmpl': os.path.join(user_upload_dir, '%(id)s.%(ext)s'),
                    'restrictfilenames': True,
                    'noplaylist': True,
                    
                    # --- FIX RETE / TIMEOUT ---
                    'compat_opts': ['no-youtube-unavailable-videos'], # Evita controlli extra lenti
                    'source_address': '0.0.0.0', # Forza IPv4 locale
                    'force_ipv4': True,          # Forza IPv4 a livello DNS (fondamentale in LXC)
                    
                    # --- FIX ANTI-BOT ---
                    'impersonate': 'chrome',
                    'extractor_args': {'youtube': ['player_client=android']} # Android è spesso più leggero del client web
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # Estrae le info e scarica
                    info_dict = ydl.extract_info(youtube_url, download=True)
                    
                    # Genera un nome file sicuro basato sul titolo per la nostra app
                    video_title = info_dict.get('title', info_dict.get('id', 'youtube_audio'))
                    safe_title = secure_filename(video_title)
                    if not safe_title:
                        safe_title = info_dict.get('id', 'youtube_audio')
                        
                    # Rinomina il file scaricato (ID.mp3) con il titolo pulito (Titolo.mp3)
                    downloaded_file = os.path.join(user_upload_dir, f"{info_dict['id']}.mp3")
                    final_filename = f"{safe_title}.mp3"
                    final_path = os.path.join(user_upload_dir, final_filename)
                    
                    # Se esiste già un file con quel nome, lo sovrascrive
                    if os.path.exists(final_path):
                        os.remove(final_path)
                    os.rename(downloaded_file, final_path)
                    
                return redirect(url_for('chose_actions', name=final_filename))
                
            except Exception as e:
                # ORA STAMPIAMO L'ERRORE ESATTO per capire cosa non va!
                print(f"Errore YouTube: {e}")
                flash(f"Errore YouTube: {str(e)}")
                return redirect(request.url)
                
        # 2. Caso B: L'utente ha caricato un file normalmente
        elif 'file' in request.files:
            file = request.files['file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(user_upload_dir, filename))
                return redirect(url_for('chose_actions', name=filename))

    # Prepariamo i file da mostrare accoppiando ZIP e Audio Ricomposto
    files_data = []
    all_files = os.listdir(user_output_dir)
    
    for f in all_files:
        if f.endswith('.zip'):
            base_name = f[:-4]
            recomposed_name = f"{base_name}_recomposed.mp3"
            has_recomposed = recomposed_name in all_files
            
            files_data.append({
                'display_name': base_name,
                'zip_file': f,
                'recomposed_file': recomposed_name if has_recomposed else None
            })
    
    user_tasks = {k: v for k, v in tasks_status.items() if v['user'] == username}

    return render_template("index.html", files=files_data, tasks=user_tasks, username=username)

# --- ACTIONS E BACKGROUND PROCESSING ---

def run_background_process(username, filename, action, task_id):
    tasks_status[task_id]['status'] = 'Estrazione tracce in corso...'
    
    user_upload_dir = get_user_dir(UPLOAD_FOLDER, username)
    user_output_dir = get_user_dir(OUTPUT_FOLDER, username)
    
    input_file_path = os.path.join(user_upload_dir, filename)
    file_base = os.path.splitext(filename)[0]
    
    target_folder_name = f"{file_base}_{action}"
    target_dir = get_unique_folder(user_output_dir, target_folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    try:
        # 1. DEMUCS
        cmd_demucs = ["demucs", "--mp3", "-o", target_dir, input_file_path]
        subprocess.run(cmd_demucs, check=True)
        
        # 2. SISTEMAZIONE FILE
        demucs_out_dir = os.path.join(target_dir, "htdemucs", file_base)
        stems = ["vocals.mp3", "bass.mp3", "drums.mp3", "other.mp3"]
        for stem in stems:
            src_path = os.path.join(demucs_out_dir, stem)
            if os.path.exists(src_path):
                shutil.move(src_path, os.path.join(target_dir, stem))
        shutil.rmtree(os.path.join(target_dir, "htdemucs"))
        
        # 3. RIASSEMBLAGGIO
        tasks_status[task_id]['status'] = 'Riassemblaggio tracce...'
        stems_to_mix = []
        if action == "no_vocals":
            stems_to_mix = ["bass.mp3", "drums.mp3", "other.mp3"]
        elif action == "no_bass":
            stems_to_mix = ["vocals.mp3", "drums.mp3", "other.mp3"]
        elif action == "no_drums":
            stems_to_mix = ["vocals.mp3", "bass.mp3", "other.mp3"]

        mixed_filepath = None
        if stems_to_mix:
            mixed_filename = f"recomposed_{action}.mp3"
            mixed_filepath = os.path.join(target_dir, mixed_filename)
            cmd_ffmpeg = ["ffmpeg", "-y"]
            for s in stems_to_mix:
                cmd_ffmpeg.extend(["-i", os.path.join(target_dir, s)])
            num_inputs = len(stems_to_mix)
            cmd_ffmpeg.extend([
                "-filter_complex", f"amix=inputs={num_inputs}:duration=longest", 
                mixed_filepath
            ])
            subprocess.run(cmd_ffmpeg, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 4. CREAZIONE DELLO ZIP (contiene tracce separate + ricomposta)
        tasks_status[task_id]['status'] = 'Creazione file ZIP...'
        # Usiamo basename di target_dir per gestire eventuali numeri _1, _2 aggiunti da get_unique_folder
        final_base_name = os.path.basename(target_dir) 
        zip_filename = final_base_name + ".zip"
        zip_filepath = os.path.join(user_output_dir, zip_filename)
        
        with zipfile.ZipFile(zip_filepath, 'w') as zipf:
            for f in os.listdir(target_dir):
                file_path = os.path.join(target_dir, f)
                if os.path.isfile(file_path):
                    zipf.write(file_path, arcname=f)
                    
        # 5. SPOSTIAMO L'AUDIO RICOMPOSTO E PULIAMO LA CARTELLA
        if mixed_filepath and os.path.exists(mixed_filepath):
            final_recomposed_name = f"{final_base_name}_recomposed.mp3"
            final_recomposed_path = os.path.join(user_output_dir, final_recomposed_name)
            shutil.copy(mixed_filepath, final_recomposed_path) # Lo copiamo fuori per permetterne il download diretto
            
        shutil.rmtree(target_dir) # Puliamo la cartella temporanea!
        
        tasks_status[task_id]['status'] = 'Completato'
        
    except subprocess.CalledProcessError as e:
        print(f"Errore processo: {e}")
        tasks_status[task_id]['status'] = 'Errore durante l\'elaborazione'
    except Exception as e:
        print(f"Errore imprevisto: {e}")
        tasks_status[task_id]['status'] = 'Errore imprevisto'

@app.route('/actions/<name>', methods=['GET', 'POST'])
def chose_actions(name):
    if 'username' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        action = request.form.get("action")
        username = session['username']
        
        task_id = f"{username}_{name}_{action}_{int(time.time())}"
        tasks_status[task_id] = {
            'user': username, 'file': name, 'action': action, 'status': 'Avviato'
        }
        
        thread = threading.Thread(target=run_background_process, args=(username, name, action, task_id))
        thread.start()
        
        flash(f'Esportazione "{action}" per {name} avviata in background!')
        return redirect(url_for('index'))
    return render_template("actions.html", filename=name)

@app.route('/download/<filename>')
def download_file(filename):
    if 'username' not in session:
        return redirect(url_for('login'))
    user_output_dir = get_user_dir(OUTPUT_FOLDER, session['username'])
    return send_from_directory(user_output_dir, filename, as_attachment=True)

@app.route('/delete/<base_name>', methods=['POST'])
def delete_file(base_name):
    if 'username' not in session:
        return redirect(url_for('login'))
        
    username = session['username']
    user_output_dir = get_user_dir(OUTPUT_FOLDER, username)
    user_upload_dir = get_user_dir(UPLOAD_FOLDER, username)
    
    # Percorsi dei file di output da eliminare
    zip_path = os.path.join(user_output_dir, f"{base_name}.zip")
    recomposed_path = os.path.join(user_output_dir, f"{base_name}_recomposed.mp3")
    
    deleted = False
    
    if os.path.exists(zip_path):
        os.remove(zip_path)
        deleted = True
        
    if os.path.exists(recomposed_path):
        os.remove(recomposed_path)
        deleted = True
        
    # Cerchiamo di dedurre il nome del file originale per eliminarlo dagli uploads.
    # Il base_name è tipicamente nel formato "nomefile_azione" (es. brano_no_vocals).
    # Risaliamo al nome rimuovendo l'azione alla fine:
    for action in ["no_vocals", "no_bass", "no_drums"]:
        if f"_{action}" in base_name:
            # Ricostruisce il nome del file base senza il suffisso dell'azione e senza eventuali _1, _2
            original_base = base_name.split(f"_{action}")[0]
            
            # Cerca se esiste un file con questo nome in formato .mp3 o .wav
            for ext in ALLOWED_EXTENSIONS:
                original_upload_path = os.path.join(user_upload_dir, f"{original_base}.{ext}")
                if os.path.exists(original_upload_path):
                    os.remove(original_upload_path)
            break

    # Pulizia del task_status per rimuoverlo anche dallo storico in background
    keys_to_delete = []
    for task_id, task_info in tasks_status.items():
        if task_info['user'] == username and base_name.startswith(task_info['file'].rsplit('.', 1)[0]):
            keys_to_delete.append(task_id)
            
    for k in keys_to_delete:
        del tasks_status[k]

    if deleted:
        flash(f'Esportazione "{base_name}" e relativi file originali eliminati con successo.')
    else:
        flash(f'Impossibile trovare l\'esportazione "{base_name}".')
        
    return redirect(url_for('index'))

# --- ROTTE DEDICATE PER APP INVENTOR ---

@app.route('/app_login')
def app_login():
    # Recupera le credenziali dall'URL
    username = request.args.get('u')
    password = request.args.get('p')

    if username and password and os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            for line in f:
                if not line.strip(): continue
                u, p = line.strip().split(',')
                if u == username and p == password:
                    # Credenziali corrette: crea la sessione e vai alla home
                    session['username'] = username
                    return redirect(url_for('index'))
                    
    # Se fallisce, lo manda alla pagina di errore dedicata
    return redirect(url_for('app_login_error'))


@app.route('/app_login_error')
def app_login_error():
    # Pagina di errore che avvisa l'utente e lo riporta al vero login del sito
    return """
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: Arial, sans-serif; background-color: #f4f4f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; text-align: center; }
                .card { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                h2 { color: #dc3545; margin-top: 0; }
                a { display: inline-block; margin-top: 15px; background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; }
                a:hover { background-color: #0056b3; }
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Errore di Accesso</h2>
                <p>Credenziali non valide o account inesistente.</p>
                <a href="/login">Vai al Login del sito</a>
            </div>
        </body>
    </html>
    """


@app.route('/app_register')
def app_register():
    # Recupera le credenziali dall'URL per la registrazione
    username = request.args.get('u')
    password = request.args.get('p')

    if not username or not password:
        return "Errore: nome utente o password mancanti nell'URL.", 400

    # Controlla se l'utente esiste già
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            for line in f:
                if not line.strip(): continue
                u, _ = line.strip().split(',')
                if u == username:
                    return """
                    <html>
                        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                            <h2 style="color: #dc3545;">Errore</h2>
                            <p>Questo nome utente è già in uso.</p>
                            <a href="/register" style="display: inline-block; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 4px;">Torna alla Registrazione</a>
                        </body>
                    </html>
                    """

    # Se l'utente non esiste, lo registra
    with open(USERS_FILE, 'a') as f:
        f.write(f"{username},{password}\n")
    
    # Lo logga automaticamente e lo manda alla home
    session['username'] = username
    flash('Registrazione da App completata con successo!')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5764)