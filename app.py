# app.py
import os
import shutil
import uuid
import zipfile
from io import BytesIO
from flask import Flask, request, render_template_string, send_file, redirect, url_for, flash
from werkzeug.utils import secure_filename

# अपने रूपांतरण लॉजिक को आयात करें
from converter_logic import run_conversion

app = Flask(__name__)
app.secret_key = os.urandom(24) # flash संदेशों के लिए आवश्यक

# प्रत्येक अनुरोध के लिए अपलोड और परिणामों के लिए अस्थायी फ़ोल्डर
UPLOAD_FOLDER = 'user_uploads_hindi' # हिंदी संस्करण के लिए अलग फ़ोल्डर
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # फ़ाइल आकार पर 30 MB की सीमा

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# फ़ॉर्म के लिए HTML टेम्पलेट
INDEX_HTML_HINDI = """
<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF से HTML परिवर्तक</title>
    <style>
        body { font-family: 'Noto Sans Devanagari', sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }
        .container { background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); max-width: 600px; margin: auto; }
        h1 { color: #333; text-align: center; }
        label { display: block; margin-top: 10px; margin-bottom: 5px; font-weight: bold;}
        input[type="password"], input[type="file"], select[multiple] {
            width: calc(100% - 22px); padding: 10px; margin-bottom: 10px;
            border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box;
        }
        input[type="submit"] {
            background-color: #007bff; color: white; padding: 10px 15px;
            border: none; border-radius: 4px; cursor: pointer; font-size: 16px; display: block; width: 100%;
        }
        input[type="submit"]:hover { background-color: #0056b3; }
        .flash-message {
            padding: 10px; margin-bottom: 15px; border-radius: 4px;
        }
        .flash-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .flash-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .loader {
            border: 8px solid #f3f3f3; /* हल्का ग्रे */
            border-top: 8px solid #3498db; /* नीला */
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
            display: none; /* डिफ़ॉल्ट रूप से छिपा हुआ */
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        #languages option { padding: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>PDF से HTML परिवर्तक (Gemini का उपयोग करके)</h1>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="flash-message flash-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="post" enctype="multipart/form-data" id="conversionForm">
            <label for="api_key">Gemini API कुंजी:</label>
            <input type="password" id="api_key" name="api_key" required>

            <label for="pdf_file">PDF फ़ाइल (अधिकतम 30MB):</label>
            <input type="file" id="pdf_file" name="pdf_file" accept=".pdf" required>

            <label for="languages">लक्ष्य भाषाएँ (एक या अधिक चुनें):</label>
            <select id="languages" name="languages" multiple required size="5">
                <option value="English" selected>अंग्रेजी (English)</option>
                <option value="Hindi">हिन्दी (Hindi)</option>
                <option value="Spanish">स्पेनिश (Español)</option>
                <option value="French">फ्रेंच (Français)</option>
                <option value="German">जर्मन (Deutsch)</option>
                <option value="Russian">रूसी (Русский)</option>
                <option value="Chinese">चीनी (中文)</option>
                <option value="Japanese">जापानी (日本語)</option>
                <option value="Arabic">अरबी (العربية)</option>
            </select>
            <p><small>एकाधिक भाषाएँ चुनने के लिए Ctrl (या Mac पर Cmd) दबाए रखें।</small></p>

            <input type="submit" value="PDF को HTML में बदलें">
        </form>
        <div id="loader" class="loader"></div>
    </div>
    <script>
        document.getElementById('conversionForm').addEventListener('submit', function() {
            document.getElementById('loader').style.display = 'block';
            document.querySelector('input[type="submit"]').disabled = true;
            document.querySelector('input[type="submit"]').value = 'प्रसंस्करण हो रहा है...';
        });
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        pdf_file = request.files.get('pdf_file')
        target_languages = request.form.getlist('languages')

        if not api_key:
            flash('Gemini API कुंजी आवश्यक है।', 'error')
            return redirect(url_for('index'))
        if not pdf_file or pdf_file.filename == '':
            flash('कोई PDF फ़ाइल नहीं चुनी गई।', 'error')
            return redirect(url_for('index'))
        if not target_languages:
            flash('कम से कम एक लक्ष्य भाषा चुननी होगी।', 'error')
            return redirect(url_for('index'))

        if pdf_file and allowed_file(pdf_file.filename):
            session_id = str(uuid.uuid4())
            session_folder = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
            # सुनिश्चित करें कि सेशन फ़ोल्डर हर बार बनाया जाए, यदि यह पहले से मौजूद नहीं है
            if not os.path.exists(session_folder):
                os.makedirs(session_folder, exist_ok=True)


            pdf_filename = secure_filename(pdf_file.filename)
            pdf_path = os.path.join(session_folder, pdf_filename)
            pdf_file.save(pdf_path)
            response_sent = False # ट्रैक करने के लिए कि क्या send_file कॉल किया गया था

            try:
                html_file_path, images_folder_path = run_conversion(
                    gemini_api_key_param=api_key,
                    pdf_file_path_param=pdf_path,
                    base_output_folder_param=session_folder,
                    target_languages_param=target_languages
                )

                zip_filename = f"{os.path.splitext(pdf_filename)[0]}_converted.zip"
                zip_buffer = BytesIO()

                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(html_file_path, os.path.basename(html_file_path))
                    if os.path.exists(images_folder_path) and os.listdir(images_folder_path):
                        for root, _, files_in_img_folder in os.walk(images_folder_path):
                            for file_in_img_folder_item in files_in_img_folder:
                                file_path_in_img_folder = os.path.join(root, file_in_img_folder_item)
                                arcname = os.path.join(os.path.basename(images_folder_path), file_in_img_folder_item)
                                zf.write(file_path_in_img_folder, arcname)
                zip_buffer.seek(0)
                flash('रूपांतरण सफल! आपका डाउनलोड शीघ्र ही शुरू होना चाहिए।', 'success')

                response = send_file(
                    zip_buffer,
                    as_attachment=True,
                    download_name=zip_filename,
                    mimetype='application/zip'
                )
                response_sent = True
                return response

            except FileNotFoundError as e:
                flash(f'त्रुटि: {e}', 'error')
                app.logger.error(f"FileNotFoundError: {e}")
            except ValueError as e:
                flash(f'कॉन्फ़िगरेशन त्रुटि: {e}', 'error')
                app.logger.error(f"ValueError: {e}")
            except Exception as e:
                flash(f'रूपांतरण के दौरान एक त्रुटि हुई: {e}', 'error')
                app.logger.error(f"रूपांतरण अपवाद: {e}", exc_info=True)
            finally:
                # सेशन फ़ोल्डर को केवल तभी हटाएं जब send_file सफल न हुआ हो
                # send_file के बाद की सफाई Render पर जटिल हो सकती है,
                # इसलिए हम इसे केवल त्रुटि के मामलों में या जब send_file नहीं हुआ हो, तब करते हैं।
                if not response_sent and os.path.exists(session_folder):
                    shutil.rmtree(session_folder)
                elif response_sent and os.path.exists(session_folder):
                    # यदि send_file हुआ है, तो हम Render को अस्थायी फ़ाइलों को स्वयं प्रबंधित करने देंगे
                    # या एक अलग सफाई तंत्र (जैसे क्रॉन जॉब) पर निर्भर रहेंगे।
                    # तुरंत हटाना send_file को बाधित कर सकता है।
                    app.logger.info(f"Session folder {session_folder} not deleted immediately after successful send_file.")


            return redirect(url_for('index'))

    return render_template_string(INDEX_HTML_HINDI)

if __name__ == '__main__':
    # Render.com PORT एनवायरनमेंट वेरिएबल सेट करेगा।
    # स्थानीय रूप से, यह 8080 पर चलेगा।
    port = int(os.environ.get('PORT', 8080))
    # Render के लिए, debug=False होना चाहिए। Gunicorn इसका ध्यान रखेगा।
    # स्थानीय परीक्षण के लिए, debug=True ठीक है।
    # Start command on Render `gunicorn app:app` होगा, इसलिए यह if __name__ ब्लॉक Render पर नहीं चलेगा।
    app.run(host='0.0.0.0', port=port, debug=False if os.environ.get('PORT') else True)
