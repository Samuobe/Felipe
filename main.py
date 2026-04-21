from flask import Flask, flash, request, redirect, url_for, render_template, send_file
from werkzeug.utils import secure_filename
import os
import zipfile

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


@app.route('/process', methods=['POST'])
def process_audio():

    action = request.form.get("action")

    if action in ["no_vocals", "no_bass", "no_drums"]:

        if action == "no_vocals":
            print("Rimuovo voce...")
            # demucs --no-vocals logic

        elif action == "no_bass":
            print("Rimuovo basso...")

        elif action == "no_drums":
            print("Rimuovo batteria...")

        return f"Operazione {action} completata!"

    elif action == "split_all":
        print("DIVIDO TUTTE LE TRACCE (STEMS COMPLETI)")
        print("-> voice stem generato")
        print("-> bass stem generato")
        print("-> drums stem generato")
        print("-> other stem generato")

        # QUI in futuro:
        # demucs --two-stems / --all-stems
        # oppure spleeter 4stems

        return "Split completo eseguito (solo log)"

    elif action == "advanced":

        keep_voice = request.form.get("keep_voice")
        keep_drums = request.form.get("keep_drums")
        keep_bass = request.form.get("keep_bass")
        keep_other = request.form.get("keep_other")
        export_zip = request.form.get("export_zip")

        print("Modalità avanzata attivata")

        stems = {
            "voice": True if keep_voice else False,
            "drums": True if keep_drums else False,
            "bass": True if keep_bass else False,
            "other": True if keep_other else False
        }

        print("Stems selezionati:", stems)

        if export_zip:
            zip_path = os.path.join(OUTPUT_FOLDER, "stems.zip")

            with zipfile.ZipFile(zip_path, "w") as zipf:
                for file in os.listdir(OUTPUT_FOLDER):
                    file_path = os.path.join(OUTPUT_FOLDER, file)
                    if os.path.isfile(file_path):
                        zipf.write(file_path, arcname=file)

            return send_file(zip_path, as_attachment=True)

        return "Processo avanzato completato!"

    return "Nessuna azione valida"
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp3', 'wav'}


app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['file']

        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return redirect(url_for('chose_actions', name=filename))

    return render_template("index.html")

@app.route('/actions/<name>', methods=['GET', 'POST'])
def chose_actions(name):
    if request.method == 'POST':
        print("E sticazzi")
    

    return render_template("actions.html")




@app.route('/download/<name>')
def download_file(name):
    return f"File caricato: {name}"


if __name__ == '__main__':
    app.run(debug=True)