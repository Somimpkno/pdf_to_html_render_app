# converter_logic.py
import fitz  # PyMuPDF
import os
import time
# google.generativeai के बजाय from google import genai का उपयोग करें
from google import genai
from google.genai import types # GenerateContentConfig के लिए जोड़ा गया
import json
from PIL import Image
import shutil # अस्थायी फ़ोल्डर हटाने के लिए

# --- नई: सेटिंग्स जो बाहर से पास की जाएंगी ---
# PDF_PATH, BASE_OUTPUT_FOLDER, TARGET_LANGUAGES, GEMINI_API_KEY आर्गुमेंट के रूप में पास किए जाएंगे

HTML_IMAGE_SUBFOLDER = "extracted_images" # HTML src के लिए सापेक्ष पथ

# --- Gemini API सेटअप (API कुंजी पास करने के लिए थोड़ा बदला गया) ---
def get_gemini_client_and_models(api_key_param):
    if not api_key_param:
        raise ValueError("GEMINI API कुंजी पैरामीटर प्रदान नहीं किया गया।")

    client = genai.Client(api_key=api_key_param)
    try:
        print(f"Gemini client प्रारंभ हो गया।")
        return client
    except Exception as e:
        print(f"Gemini client प्रारंभ नहीं किया जा सका। त्रुटि: {e}")
        raise

# converter_logic.py में (extract_images_and_generate_alt_tags फ़ंक्शन के अंदर)

def extract_images_and_generate_alt_tags(gemini_client, vision_model_name_param, pdf_path, output_images_folder, target_languages):
    print(f"DEBUG: extract_images_and_generate_alt_tags फ़ंक्शन शुरू हो रहा है PDF: {pdf_path}") # डिबग
    if not os.path.exists(pdf_path):
        print(f"PDF नहीं मिला: {pdf_path}.")
        return []

    doc = None # doc को पहले None पर सेट करें
    try: # fitz.open() के लिए try-except ब्लॉक जोड़ें
        doc = fitz.open(pdf_path)
    except Exception as e_open:
        print(f"DEBUG: PDF खोलने में त्रुटि ({pdf_path}): {e_open}")
        return []
        
    images_data = []
    image_extraction_counter = 0

    if not os.path.exists(output_images_folder):
        os.makedirs(output_images_folder, exist_ok=True)
    
    print(f"DEBUG: PDF में पृष्ठों की संख्या: {len(doc)}") # डिबग

    for page_num in range(len(doc)):
        page_index_for_log = page_num + 1 # लॉगिंग के लिए 1-आधारित सूचकांक
        print(f"\nDEBUG: पृष्ठ {page_index_for_log} को संसाधित किया जा रहा है...") # डिबग
        page = doc[page_num]
        
        # page.get_images() का उपयोग करके छवियों की सूची प्राप्त करने का प्रयास करें
        image_list = []
        try:
            image_list = page.get_images(full=True)
        except Exception as e_get_images:
            print(f"DEBUG: पृष्ठ {page_index_for_log} से get_images() में त्रुटि: {e_get_images}")
            continue # अगले पृष्ठ पर जाएँ

        print(f"DEBUG: पृष्ठ {page_index_for_log} पर मिली संभावित छवियों की संख्या: {len(image_list)}") # डिबग

        if not image_list:
            print(f"DEBUG: पृष्ठ {page_index_for_log} पर कोई छवि (get_images द्वारा) नहीं मिली।")
            # वैकल्पिक तरीका: page.get_drawings() का उपयोग करके चित्र निकालने का प्रयास करें
            # यह वेक्टर ग्राफिक्स को रास्टराइज़ कर सकता है
            try:
                print(f"DEBUG: पृष्ठ {page_index_for_log} पर page.get_drawings() का उपयोग करने का प्रयास किया जा रहा है...")
                drawings = page.get_drawings()
                if drawings:
                    print(f"DEBUG: पृष्ठ {page_index_for_log} पर {len(drawings)} चित्र (drawings) मिले।")
                    for i, drawing_path in enumerate(drawings):
                        try:
                            # चित्र को पिक्समैप में बदलें
                            # rect = drawing_path.rect # चित्र का बाउंडिंग बॉक्स
                            # यदि drawing_path में rect एट्रिब्यूट नहीं है, तो पृष्ठ के क्लिप बाउंड का उपयोग करें
                            rect = drawing_path.get("rect", page.rect) if isinstance(drawing_path, dict) else drawing_path.rect

                            # DPI को समायोजित करके छवि की गुणवत्ता में सुधार किया जा सकता है
                            zoom_matrix = fitz.Matrix(2.0, 2.0) # 2x ज़ूम (144 DPI)
                            pix = page.get_pixmap(matrix=zoom_matrix, clip=rect)
                            
                            image_extraction_counter += 1
                            image_filename = f"page_{page_index_for_log}_drawing_{i+1}_gidx_{image_extraction_counter}.png" # हमेशा PNG के रूप में सहेजें
                            local_image_path = os.path.join(output_images_folder, image_filename)
                            
                            pix.save(local_image_path)
                            print(f"DEBUG: पृष्ठ {page_index_for_log} से चित्र को सहेजा गया: {local_image_path}")

                            alt_text = f"Drawing {i+1} from page {page_index_for_log}" # प्लेसहोल्डर ऑल्ट टेक्स्ट
                            if gemini_client and vision_model_name_param:
                                alt_text = generate_alt_text_for_local_image(gemini_client, vision_model_name_param, local_image_path, target_languages)
                            
                            html_relative_path = os.path.join(HTML_IMAGE_SUBFOLDER, image_filename)
                            images_data.append({
                                "pdf_page_num": page_index_for_log,
                                "image_index_on_page": i + 1, # यह अब पृष्ठ पर चित्र का सूचकांक है
                                "html_src_path": html_relative_path,
                                "alt_text": alt_text,
                                "extraction_method": "drawing_to_pixmap" # निष्कर्षण विधि को ट्रैक करें
                            })
                        except Exception as e_drawing:
                            print(f"DEBUG: पृष्ठ {page_index_for_log} पर चित्र {i+1} को संसाधित करने में त्रुटि: {e_drawing}")
                else:
                    print(f"DEBUG: पृष्ठ {page_index_for_log} पर कोई चित्र (drawings) नहीं मिला।")
            except Exception as e_get_drawings:
                print(f"DEBUG: पृष्ठ {page_index_for_log} से get_drawings() में त्रुटि: {e_get_drawings}")
            continue # image_list खाली होने पर अगले पृष्ठ पर जाएँ

        page_image_index = 0
        for img_info in image_list:
            xref = img_info[0]
            print(f"DEBUG: पृष्ठ {page_index_for_log}, छवि xref: {xref}") # डिबग
            base_image = None
            try:
                base_image = doc.extract_image(xref)
            except Exception as e_extract:
                print(f"DEBUG: xref {xref} निकालने में त्रुटि: {e_extract}")
                continue # अगली छवि पर जाएँ

            if not base_image or not base_image.get("image"):
                print(f"DEBUG: पृष्ठ {page_index_for_log} पर xref {xref} के लिए छवि डेटा नहीं निकाला जा सका (base_image खाली है)।")
                continue

            image_bytes = base_image["image"]
            image_ext = base_image.get("ext", "png")

            if image_ext == "jp2":
                try:
                    from io import BytesIO # सुनिश्चित करें कि यह आयातित है
                    temp_img = Image.open(BytesIO(image_bytes))
                    output_bytes_io = BytesIO()
                    temp_img.save(output_bytes_io, format="PNG")
                    image_bytes = output_bytes_io.getvalue()
                    image_ext = "png"
                    print(f"DEBUG: xref {xref} (JP2) को PNG में परिवर्तित किया गया।")
                except Exception as e_conv:
                    print(f"DEBUG: xref {xref} (JP2) को परिवर्तित करने में त्रुटि: {e_conv}")
            
            image_extraction_counter += 1
            page_image_index += 1

            image_filename = f"page_{page_index_for_log}_img_{page_image_index}_gidx_{image_extraction_counter}.{image_ext}"
            local_image_path = os.path.join(output_images_folder, image_filename)

            try:
                with open(local_image_path, "wb") as img_file:
                    img_file.write(image_bytes)
                print(f"DEBUG: छवि सहेजी गई: {local_image_path}")
            except Exception as e_save:
                print(f"DEBUG: छवि सहेजने में त्रुटि ({local_image_path}): {e_save}")
                continue

            alt_text = f"Image {page_image_index} from page {page_index_for_log}" # प्लेसहोल्डर
            if gemini_client and vision_model_name_param:
                try:
                    alt_text = generate_alt_text_for_local_image(gemini_client, vision_model_name_param, local_image_path, target_languages)
                except Exception as e_alt_text:
                    print(f"DEBUG: ऑल्ट टेक्स्ट जनरेशन में त्रुटि ({local_image_path}): {e_alt_text}")
            
            html_relative_path = os.path.join(HTML_IMAGE_SUBFOLDER, image_filename)

            images_data.append({
                "pdf_page_num": page_index_for_log,
                "image_index_on_page": page_image_index,
                "html_src_path": html_relative_path,
                "alt_text": alt_text,
                "extraction_method": "get_images" # निष्कर्षण विधि को ट्रैक करें
            })
            print(f"निकाला गया (get_images): {local_image_path} (पृष्ठ: {page_index_for_log}, पृष्ठ पर सूचकांक: {page_image_index}), ऑल्ट: '{alt_text}'")
    
    if doc: # सुनिश्चित करें कि doc बंद करने से पहले मौजूद है
        try:
            doc.close()
        except Exception as e_close:
            print(f"DEBUG: PDF बंद करने में त्रुटि: {e_close}")
            
    print(f"DEBUG: extract_images_and_generate_alt_tags फ़ंक्शन समाप्त, कुल {len(images_data)} छवियां निकाली गईं।") # डिबग
    return images_data

def extract_images_and_generate_alt_tags(gemini_client, vision_model_name_param, pdf_path, output_images_folder, target_languages):
    if not os.path.exists(pdf_path):
        print(f"PDF नहीं मिला: {pdf_path}.")
        return []

    doc = fitz.open(pdf_path)
    images_data = []
    image_extraction_counter = 0

    if not os.path.exists(output_images_folder):
        os.makedirs(output_images_folder, exist_ok=True)

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        if not image_list:
            continue

        page_image_index = 0
        for img_info in image_list:
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            if not base_image or not base_image.get("image"):
                print(f"पृष्ठ {page_num + 1} पर xref {xref} के लिए छवि डेटा नहीं निकाला जा सका")
                continue

            image_bytes = base_image["image"]
            image_ext = base_image.get("ext", "png") # डिफ़ॉल्ट रूप से png

            # कुछ PDF में "jp2" (JPEG2000) छवियां हो सकती हैं जिन्हें PIL सीधे नहीं खोल सकता
            # यदि आवश्यक हो तो उन्हें png/jpg में बदलने का प्रयास करें
            if image_ext == "jp2":
                try:
                    temp_img = Image.open(BytesIO(image_bytes))
                    # PNG में परिवर्तित करें क्योंकि यह दोषरहित है और व्यापक रूप से समर्थित है
                    output_bytes_io = BytesIO()
                    temp_img.save(output_bytes_io, format="PNG")
                    image_bytes = output_bytes_io.getvalue()
                    image_ext = "png"
                    print(f"  xref {xref} (JP2) को PNG में परिवर्तित किया गया।")
                except Exception as e_conv:
                    print(f"  xref {xref} (JP2) को परिवर्तित करने में त्रुटि: {e_conv}. मूल बाइट्स का उपयोग किया जा रहा है।")
                    # यदि रूपांतरण विफल रहता है, तो मूल एक्सटेंशन का उपयोग करें, लेकिन ऑल्ट टेक्स्ट जनरेशन विफल हो सकता है

            image_extraction_counter += 1
            page_image_index += 1

            image_filename = f"page_{page_num + 1}_idx_{page_image_index}_gidx_{image_extraction_counter}.{image_ext}"
            local_image_path = os.path.join(output_images_folder, image_filename)

            with open(local_image_path, "wb") as img_file:
                img_file.write(image_bytes)
            
            # ऑल्ट टेक्स्ट जनरेशन को वैकल्पिक बनाया जा सकता है या एक सरल प्लेसहोल्डर का उपयोग किया जा सकता है
            # यदि vision_model_name_param None है, तो ऑल्ट टेक्स्ट जनरेशन छोड़ दें
            if gemini_client and vision_model_name_param:
                alt_text = generate_alt_text_for_local_image(gemini_client, vision_model_name_param, local_image_path, target_languages)
            else:
                alt_text = f"Image {image_extraction_counter} from page {page_num + 1}"


            html_relative_path = os.path.join(HTML_IMAGE_SUBFOLDER, image_filename)

            images_data.append({
                "pdf_page_num": page_num + 1,
                "image_index_on_page": page_image_index,
                "html_src_path": html_relative_path,
                "alt_text": alt_text,
            })
            print(f"निकाला गया: {local_image_path} (पृष्ठ: {page_num+1}, पृष्ठ पर सूचकांक: {page_image_index}), ऑल्ट: '{alt_text}'")
    doc.close()
    return images_data

def generate_html_from_pdf_gemini_direct_img(gemini_client, text_model_name_param, uploaded_pdf_file_object, images_metadata_list, target_languages):
    print(f"PDF से HTML जेनरेट किया जा रहा है: {uploaded_pdf_file_object.name}")
    # सुनिश्चित करें कि यदि target_languages खाली है तो कोई त्रुटि न हो
    effective_target_languages = target_languages if target_languages else ["English"]
    print(f"आउटपुट के लिए लक्ष्य भाषाएँ: {', '.join(effective_target_languages)}")
    print(f"ऑल्ट टेक्स्ट के साथ {len(images_metadata_list)} पूर्व-निकाली गई छवियों का उपयोग किया जा रहा है।")

    images_metadata_json = json.dumps(images_metadata_list, indent=2, ensure_ascii=False)

    language_instructions = ""
    if len(effective_target_languages) == 1:
        language_instructions = f"संपूर्ण HTML सामग्री, सभी टेक्स्ट सहित, {effective_target_languages[0]} में होनी चाहिए।"
    elif len(effective_target_languages) > 1:
        langs_str = " और ".join(effective_target_languages)
        language_instructions = f"""संपूर्ण HTML सामग्री {langs_str} दोनों में प्रस्तुत की जानी चाहिए।
टेक्स्ट सामग्री के प्रत्येक भाग के लिए (उदाहरण के लिए, पैराग्राफ, सूची आइटम, हेडिंग), पहले इसे {effective_target_languages[0]} में प्रस्तुत करें, उसके तुरंत बाद {effective_target_languages[1]} में इसका अनुवाद (और अधिक भाषाओं के लिए इसी तरह)।
एक पैराग्राफ के लिए उदाहरण:
<p>This is the English text.</p>
<p>यह हिंदी में पाठ है।</p>
पूरे दस्तावेज़ में इस बिंदु-दर-बिंदु या खंड-दर-खंड द्विभाषी (या बहुभाषी) प्रस्तुति को बनाए रखें।
"""

    head_content = f"""<meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF सामग्री ({', '.join(effective_target_languages)})</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;700&family=Roboto:wght@400;700&display=swap" rel="stylesheet">
    <script>
        window.MathJax = {{
          tex: {{
            inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
            displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
          }},
          chtml: {{
            matchFontHeight: false,
            mtextInheritFont: true
          }},
          svg: {{
            mtextInheritFont: true
          }}
        }};
    </script>
    <script type="text/javascript" id="MathJax-script" async
      src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js">
    </script>
    <style>
      body {{ font-family: 'Roboto', 'Noto Sans Devanagari', sans-serif; margin: 20px; line-height: 1.6; }}
      .scrollable-table-wrapper {{ overflow-x: auto; margin-bottom: 1em; border: 1px solid #ddd; }}
      table {{ border-collapse: collapse; width: 100%; min-width: 600px; }}
      th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }}
      th {{ background-color: #f2f2f2; }}
      img {{ max-width: 100%; height: auto; display: block; margin: 1em auto; border: 1px solid #eee;}}
      h1, h2, h3, h4, h5, h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
      p {{ margin-bottom: 1em; }}
      ul, ol {{ margin-bottom: 1em; padding-left: 40px; }}
      li {{ margin-bottom: 0.5em; }}
      .page-break {{ page-break-after: always; border-bottom: 1px dashed #ccc; margin-bottom: 20px; }}
      /* यदि एक से अधिक भाषाएँ हैं, तो प्रत्येक भाषा के लिए अलग स्टाइलिंग की जा सकती है */
      .lang-en {{ /* अंग्रेजी के लिए स्टाइल */ }}
      .lang-hi {{ font-family: 'Noto Sans Devanagari', sans-serif; /* हिंदी के लिए स्टाइल */ }}
      /* अन्य भाषाओं के लिए भी इसी तरह जोड़ सकते हैं */
    </style>"""

    system_instruction_parts = [
        types.Part.from_text(f"""आप एक विशेषज्ञ PDF से HTML कनवर्टर हैं।
आपका प्राथमिक लक्ष्य प्रदान की गई PDF सामग्री (फ़ाइल इनपुट के रूप में दी गई) और संबंधित छवि जानकारी (संरचित टेक्स्ट/JSON के रूप में दी गई) को एक एकल, सुव्यवस्थित और वैध HTML फ़ाइल में परिवर्तित करना है।
HTML को PDF से टेक्स्ट सामग्री, सामान्य लेआउट, टेबल, सूचियाँ और हेडिंग को सटीक रूप से दोहराना चाहिए।
केवल मूल PDF में मौजूद सामग्री और जानकारी का उपयोग करें। कोई नया डेटा, राय या बाहरी जानकारी न जोड़ें।

**भाषा आउटपुट:**
{language_instructions}
यदि एकाधिक भाषाएँ हैं, तो प्रत्येक भाषा के टेक्स्ट को एक `<span>` या `<p>` टैग में क्लास के साथ रैप करें, जैसे `<p class="lang-en">English text</p><p class="lang-hi">हिंदी पाठ</p>`।

**HTML स्वरूपण नियम:**
1.  **केवल शुद्ध HTML टैग का उपयोग करें।** कोई मार्कडाउन सिंटैक्स नहीं।
2.  **संरचना:** पूर्ण HTML दस्तावेज़ (`<!DOCTYPE html>`, `<html>`, `<head>`, `<body>`)। `<head>` अनुभाग में अनिवार्य रूप से शामिल होना चाहिए:
{head_content}
3.  **समीकरण:** MathJax संगत LaTeX का उपयोग करें। इनलाइन: `\\( ... \\)` या `$ ... $`। डिस्प्ले: `\\[ ... \\]` या `$$ ... $$`।
    उदाहरण: `<p style="text-align:center;">$\\text{{लवण सूचकांक}} = (\\text{{कुल Na}} - 24.5) - [(\\text{{कुल Ca}} - \\text{{Ca in }} CaCO_3) \\times 4.85]$</p>`
    सुनिश्चित करें कि समीकरणों के भीतर टेक्स्ट (`\\text{{...}}`) MathJax द्वारा सही ढंग से प्रस्तुत किया गया है। यदि समीकरण में हिंदी टेक्स्ट है, तो उसे भी `\\text{{...}}` में रैप करें।
4.  **टेबल:** PDF टेबल को HTML `<table>` में बदलें। चौड़ी टेबल को `<div class="scrollable-table-wrapper">...</div>` में लपेटें।
5.  **टेक्स्ट संरक्षण:** PDF में दिखाई देने वाले सभी टेक्स्ट को ठीक वैसे ही सुरक्षित रखें, फिर भाषा निर्देशों के अनुसार अनुवाद/प्रस्तुत करें।
6.  **आरेख (गैर-छवि):** यदि PDF में टेक्स्ट, लाइनों या आकृतियों (वास्तविक बिटमैप छवियों नहीं) से बने आरेख हैं, तो उनकी संरचना को सिमेंटिक HTML का उपयोग करके दोहराने का प्रयास करें। यदि बहुत जटिल है, तो संक्षेप में वर्णन करें।
7.  **पृष्ठ पृथक्करण:** यदि संभव हो तो PDF में पृष्ठ विरामों की पहचान करें और उन्हें HTML में `<hr class="page-break">` के साथ प्रस्तुत करें।

**छवि हैंडलिंग - महत्वपूर्ण:**
आपको पूर्व-निकाली गई छवि मेटाडेटा की एक JSON सूची प्रदान की गई है।
जब आप PDF सामग्री में किसी छवि की स्थिति की पहचान करते हैं:
- आपको प्रदान किए गए मेटाडेटा का उपयोग करके एक `<img>` टैग सम्मिलित करना होगा: `<img src="{images_metadata_list[0]['html_src_path'] if images_metadata_list else 'placeholder.png'}" alt="{images_metadata_list[0]['alt_text'] if images_metadata_list else 'Image'}" style="max-width:100%; height:auto; display:block; margin:1em auto;">` (यह केवल एक उदाहरण है, आपको सही छवि से मिलान करना होगा)।
- PDF संदर्भ से छवि को मेटाडेटा से `pdf_page_num` और `image_index_on_page` से मिलाएं।

**Image Metadata (use this to insert <img> tags):**
```json
{images_metadata_json}
```

केवल पूर्ण HTML कोड के साथ प्रतिक्रिया दें। HTML से पहले या बाद में कोई स्पष्टीकरण शामिल न करें।
""")
    ]

    user_task_prompt_parts = [
        types.Part.from_uri(
            mime_type=uploaded_pdf_file_object.mime_type,
            uri=uploaded_pdf_file_object.uri
        ),
        types.Part.from_text(f"""कृपया संपूर्ण PDF (इस प्रॉम्प्ट के फ़ाइल इनपुट भाग के रूप में प्रदान की गई) को एक एकल HTML फ़ाइल में परिवर्तित करें।
सिस्टम प्रॉम्प्ट में दिए गए सभी निर्देशों का ठीक से पालन करें।
भाषा प्रस्तुति: {', '.join(effective_target_languages)}.
केवल शुद्ध HTML टैग का उपयोग करना (कोई मार्कडाउन नहीं)।
प्रदान किए गए छवि मेटाडेटा JSON का उपयोग करके सीधे `<img>` टैग डालना।
PDF के सभी पृष्ठों को संसाधित करें।
""")
    ]

    contents_for_generation = [
        types.Content(role="user", parts=user_task_prompt_parts)
    ]

    print("Gemini को HTML जनरेशन के लिए अनुरोध भेजा जा रहा है...")
    html_output_chunks = []
    try:
        actual_text_model_name = f"models/{text_model_name_param}" if not text_model_name_param.startswith("models/") else text_model_name_param
        print(f"HTML जनरेशन के लिए टेक्स्ट मॉडल का उपयोग किया जा रहा है: {actual_text_model_name}")

        # अधिकतम आउटपुट टोकन बढ़ाने का प्रयास करें यदि सामग्री कट रही है
        generation_config_params = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="text/plain"
            # max_output_tokens=8192 # यदि आवश्यक हो तो इसे अनकमेंट करें और समायोजित करें
        )

        response_stream = gemini_client.models.generate_content_stream(
            model=actual_text_model_name,
            contents=contents_for_generation,
            generation_config=generation_config_params,
            system_instruction=types.Content(role="system", parts=system_instruction_parts) if system_instruction_parts else None
        )
        for chunk in response_stream:
            # जाँचें कि क्या उम्मीदवार मौजूद हैं और उनमें सामग्री है
            if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                 html_output_chunks.append(chunk.candidates[0].content.parts[0].text)
            elif hasattr(chunk, 'text') and chunk.text: # पुराने API या अन्य प्रतिक्रिया प्रारूपों के लिए फ़ॉलबैक
                 html_output_chunks.append(chunk.text)
            
            # ब्लॉक होने की स्थिति में प्रतिक्रिया की जाँच करें
            if chunk.prompt_feedback and chunk.prompt_feedback.block_reason:
                block_reason_message = f"सामग्री जनरेशन अवरुद्ध। कारण: {chunk.prompt_feedback.block_reason}."
                if chunk.prompt_feedback.safety_ratings:
                    block_reason_message += f" सुरक्षा रेटिंग: {chunk.prompt_feedback.safety_ratings}"
                print(block_reason_message)
                raise Exception(block_reason_message)

        html_output = "".join(html_output_chunks)
        if not html_output.strip(): # यदि आउटपुट खाली है
             raise Exception("Gemini से खाली HTML प्रतिक्रिया मिली।")


    except Exception as e:
        print(f"Gemini HTML जनरेशन के दौरान त्रुटि: {e}")
        # यदि प्रॉम्प्ट फीडबैक त्रुटि में मौजूद है, तो उसे प्रिंट करें
        current_exception_response = getattr(e, 'response', None) # google.api_core.exceptions.GoogleAPIError में हो सकता है
        if current_exception_response and hasattr(current_exception_response, 'prompt_feedback') and current_exception_response.prompt_feedback.block_reason:
            print(f"प्रॉम्प्ट फीडबैक (त्रुटि से): {current_exception_response.prompt_feedback}")
        
        # त्रुटि HTML में head_content शामिल करें
        error_head = f"""<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>रूपांतरण त्रुटि</title>
        <style>body {{font-family: sans-serif; margin: 20px;}} .error-message {{color: red; border: 1px solid red; padding: 10px;}}</style>"""
        return f"<html><head>{error_head}</head><body><h1>HTML जेनरेट करने में त्रुटि</h1><p class='error-message'>विवरण: {e}</p></body></html>"

    # HTML रैपर हटाएँ यदि मॉडल ने उन्हें जोड़ा है
    if html_output.strip().startswith("```html"):
        html_output = html_output.split("```html", 1)[-1].strip()
        if html_output.endswith("```"):
            html_output = html_output.rsplit("```", 1)[0].strip()
    elif html_output.strip().startswith("```"): # कभी-कभी केवल ``` से शुरू होता है
         html_output = html_output.split("```",1)[-1].strip()
         if html_output.endswith("```"):
            html_output = html_output.rsplit("```", 1)[0].strip()


    print("Gemini से HTML जनरेशन पूर्ण।")
    return html_output.strip()

def finalize_html(html_content, target_languages):
    print("HTML पर अंतिम समायोजन किया जा रहा है...")
    effective_target_languages = target_languages if target_languages else ["English"]
    primary_lang_code = effective_target_languages[0].lower()[:2] if effective_target_languages else "en"


    head_content_template = f"""<meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF सामग्री ({', '.join(effective_target_languages)})</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;700&family=Roboto:wght@400;700&display=swap" rel="stylesheet">
    <script>
        window.MathJax = {{
          tex: {{
            inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
            displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
          }},
          chtml: {{
            matchFontHeight: false,
            mtextInheritFont: true
          }},
          svg: {{
            mtextInheritFont: true
          }}
        }};
    </script>
    <script type="text/javascript" id="MathJax-script" async
      src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js">
    </script>
    <style>
      body {{ font-family: 'Roboto', 'Noto Sans Devanagari', sans-serif; margin: 20px; line-height: 1.6; }}
      .scrollable-table-wrapper {{ overflow-x: auto; margin-bottom: 1em; border: 1px solid #ddd; }}
      table {{ border-collapse: collapse; width: 100%; min-width: 600px; }}
      th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }}
      th {{ background-color: #f2f2f2; }}
      img {{ max-width: 100%; height: auto; display: block; margin: 1em auto; border: 1px solid #eee;}}
      h1, h2, h3, h4, h5, h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
      p {{ margin-bottom: 1em; }}
      ul, ol {{ margin-bottom: 1em; padding-left: 40px; }}
      li {{ margin-bottom: 0.5em; }}
      .page-break {{ page-break-after: always; border-bottom: 1px dashed #ccc; margin-bottom: 20px; }}
      .lang-en {{ /* अंग्रेजी के लिए स्टाइल */ }}
      .lang-hi {{ font-family: 'Noto Sans Devanagari', sans-serif; /* हिंदी के लिए स्टाइल */ }}
    </style>"""

    # सुनिश्चित करें कि DOCTYPE सबसे ऊपर है
    html_lower = html_content.lower()
    if not html_lower.strip().startswith("<!doctype html>"):
        # यदि DOCTYPE नहीं है, लेकिन <html> है, तो DOCTYPE को <html> के पहले डालें
        if "<html" in html_lower:
            html_tag_index = html_lower.find("<html")
            html_content = "<!DOCTYPE html>\n" + html_content[html_tag_index:]
        else: # यदि न DOCTYPE है, न <html>, तो सब कुछ रैप करें
            html_content = f"<!DOCTYPE html>\n<html lang=\"{primary_lang_code}\"><head>{head_content_template}</head><body>{html_content}</body></html>"
    
    # यदि DOCTYPE है, लेकिन <html> टैग नहीं है, या lang एट्रिब्यूट नहीं है
    if html_lower.strip().startswith("<!doctype html>") and ("<html" not in html_lower or f"<html lang=\"{primary_lang_code}\"" not in html_lower):
        if "<html" in html_lower: # यदि <html> है, तो lang एट्रिब्यूट जोड़ें/बदलें
            import re
            html_content = re.sub(r"<html[^>]*>", f"<html lang=\"{primary_lang_code}\">", html_content, count=1, flags=re.IGNORECASE)
        else: # यदि <html> नहीं है, तो doctype के बाद जोड़ें
            doctype_end_index = html_lower.find("<!doctype html>") + len("<!doctype html>")
            html_content = html_content[:doctype_end_index] + f"\n<html lang=\"{primary_lang_code}\">" + html_content[doctype_end_index:] + "\n</html>"


    # सुनिश्चित करें कि <head> और <body> टैग मौजूद हैं और <head> में आवश्यक सामग्री है
    if "<head>" not in html_lower:
        if "<body" in html_lower: # यदि <body> है, तो <head> को उससे पहले डालें
            body_tag_index = html_lower.find("<body")
            html_content = html_content[:body_tag_index] + f"<head>\n{head_content_template}\n</head>\n" + html_content[body_tag_index:]
        else: # यदि <body> भी नहीं है, तो <head> और <body> दोनों से रैप करें (<html> पहले से ही होना चाहिए)
            html_body_content = html_content.split(f"<html lang=\"{primary_lang_code}\">",1)[1].rsplit("</html>",1)[0]
            html_content = f"<!DOCTYPE html>\n<html lang=\"{primary_lang_code}\"><head>\n{head_content_template}\n</head>\n<body>{html_body_content}</body>\n</html>"
    elif "<meta charset=\"UTF-8\">" not in html_content : # यदि <head> है लेकिन खाली या अपूर्ण है
        head_end_tag_index = html_lower.find("</head>")
        if head_end_tag_index != -1:
            # <head> के अंदर की मौजूदा सामग्री को सुरक्षित रखने का प्रयास करें
            head_start_tag_index = html_lower.find("<head>") + len("<head>")
            existing_head_content = html_content[head_start_tag_index:head_end_tag_index]
            # केवल तभी जोड़ें यदि यह पहले से मौजूद नहीं है
            if "<meta charset=\"UTF-8\">" not in existing_head_content:
                html_content = html_content[:head_start_tag_index] + "\n" + head_content_template + "\n" + existing_head_content + html_content[head_end_tag_index:]
            # यदि MathJax स्क्रिप्ट पहले से मौजूद है, तो उसे दोबारा न जोड़ें
            elif '<script type="text/javascript" id="MathJax-script"' not in existing_head_content:
                 # केवल MathJax स्क्रिप्ट जोड़ें, बाकी स्टाइल आदि पहले से हो सकते हैं
                 mathjax_script = """<script>
        window.MathJax = {{
          tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] }},
          chtml: {{ matchFontHeight: false, mtextInheritFont: true }},
          svg: {{ mtextInheritFont: true }}
        }};
    </script>
    <script type="text/javascript" id="MathJax-script" async
      src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js">
    </script>"""
                 html_content = html_content[:head_end_tag_index] + "\n" + mathjax_script + "\n" + html_content[head_end_tag_index:]


    print("HTML समायोजन पूर्ण।")
    return html_content.strip()

def run_conversion(gemini_api_key_param, pdf_file_path_param, base_output_folder_param, target_languages_param):
    print(f"PDF से HTML रूपांतरण प्रक्रिया शुरू हो रही है (भाषाएँ: {', '.join(target_languages_param)})...")

    vision_model_name = "gemini-pro-vision"
    # पाठ मॉडल के लिए नवीनतम स्थिर संस्करण का उपयोग करना बेहतर है
    text_model_name = "gemini-1.5-flash-latest" # या "gemini-1.5-pro-latest"

    extracted_images_folder = os.path.join(base_output_folder_param, HTML_IMAGE_SUBFOLDER) # सापेक्ष पथ का उपयोग करें
    final_html_file_path = os.path.join(base_output_folder_param, "final_output.html")

    # सुनिश्चित करें कि base_output_folder_param मौजूद है
    if not os.path.exists(base_output_folder_param):
         os.makedirs(base_output_folder_param, exist_ok=True)
    # सुनिश्चित करें कि extracted_images_folder मौजूद है
    if not os.path.exists(extracted_images_folder):
        os.makedirs(extracted_images_folder, exist_ok=True)


    gemini_client = None
    try:
        gemini_client = get_gemini_client_and_models(gemini_api_key_param)
    except ValueError as e:
        print(f"Gemini प्रारंभ करने में गंभीर त्रुटि: {e}")
        raise
    except Exception as e_gen:
        print(f"Gemini सेटअप के दौरान एक सामान्य त्रुटि हुई: {e_gen}")
        raise

    print("\n--- चरण 1: छवियाँ निकालना और ऑल्ट टैग जेनरेट करना ---")
    # यदि उपयोगकर्ता बहुत तेज़ परिणाम चाहता है तो vision_model_name को None पास करें
    # current_vision_model = vision_model_name # ऑल्ट टेक्स्ट जनरेशन सक्षम
    current_vision_model = None # ऑल्ट टेक्स्ट जनरेशन अक्षम (तेज़)
    images_metadata = extract_images_and_generate_alt_tags(
        gemini_client, current_vision_model, pdf_file_path_param,
        extracted_images_folder, target_languages_param
    )
    if not images_metadata:
        print("कोई छवि नहीं निकाली गई या छवि मेटाडेटा खाली है।")
    else:
        print(f"सफलतापूर्वक {len(images_metadata)} छवियाँ संसाधित की गईं।")

    print("\n--- चरण 2: HTML जनरेशन के लिए PDF को Gemini पर अपलोड करना ---")
    uploaded_pdf_file = None
    if not os.path.exists(pdf_file_path_param):
        print(f"गंभीर त्रुटि: PDF फ़ाइल {pdf_file_path_param} मौजूद नहीं है।")
        raise FileNotFoundError(f"PDF फ़ाइल {pdf_file_path_param} मौजूद नहीं है।")

    try:
        print(f"PDF अपलोड करने का प्रयास किया जा रहा है: {pdf_file_path_param}")
        # प्रदर्शन नाम में समय टिकट जोड़ें ताकि यह अद्वितीय हो
        unique_display_name = f"{os.path.basename(pdf_file_path_param)}-{int(time.time())}"
        uploaded_pdf_file = gemini_client.files.upload(
            path=pdf_file_path_param,
            display_name=unique_display_name
        )

        if not uploaded_pdf_file:
            print("PDF अपलोड विफल, client.files.upload ने None लौटाया।")
            raise Exception("PDF अपलोड विफल")

        print(f"PDF अपलोड शुरू किया गया। फ़ाइल का नाम: {uploaded_pdf_file.name}, URI: {uploaded_pdf_file.uri}, स्थिति: {uploaded_pdf_file.state.name}")

        polling_interval = 7 # थोड़ा और समय दें
        max_wait_time = 180 # बड़े PDF के लिए प्रतीक्षा समय बढ़ाएँ
        elapsed_time = 0

        while uploaded_pdf_file.state.name == "PROCESSING" and elapsed_time < max_wait_time:
            print(f"PDF फ़ाइल '{uploaded_pdf_file.name}' की प्रतीक्षा की जा रही है (स्थिति: {uploaded_pdf_file.state.name})... {polling_interval}सेकंड प्रतीक्षा कर रहे हैं")
            time.sleep(polling_interval)
            elapsed_time += polling_interval
            updated_file_status = gemini_client.files.get(name=uploaded_pdf_file.name)
            if updated_file_status:
                 uploaded_pdf_file = updated_file_status
            else:
                 print(f"{uploaded_pdf_file.name} के लिए स्थिति पुनः प्राप्त करने में विफल। प्रतीक्षा निरस्त।")
                 break

        if uploaded_pdf_file.state.name == "ACTIVE":
            print(f"PDF '{uploaded_pdf_file.name}' सक्रिय है और तैयार है।")
        else:
            error_message = f"PDF अपलोड विफल या सक्रिय नहीं हुआ। अंतिम स्थिति: {uploaded_pdf_file.state.name} {elapsed_time}सेकंड के बाद।"
            # यदि फ़ाइल ऑब्जेक्ट में त्रुटि ऑब्जेक्ट है तो उसे एक्सेस करने का प्रयास करें
            file_error = getattr(uploaded_pdf_file, 'error', None)
            if file_error and hasattr(file_error, 'message'):
                error_message += f" त्रुटि: {file_error.message}"
            elif file_error:
                 error_message += f" त्रुटि: {file_error}"
            print(error_message)

            # यदि फ़ाइल का नाम है तो उसे हटाने का प्रयास करें
            if uploaded_pdf_file and hasattr(uploaded_pdf_file, 'name') and uploaded_pdf_file.name:
                try:
                    print(f"विफल/अटकी हुई फ़ाइल को हटाने का प्रयास किया जा रहा है: {uploaded_pdf_file.name}")
                    gemini_client.files.delete(name=uploaded_pdf_file.name)
                    print(f"फ़ाइल {uploaded_pdf_file.name} साफ की गई।")
                except Exception as e_del_fail:
                    print(f"विफलता के बाद फ़ाइल {uploaded_pdf_file.name} को नहीं हटाया जा सका: {e_del_fail}")
            raise Exception(error_message)

    except Exception as e:
        print(f"PDF अपलोड/प्रसंस्करण के दौरान त्रुटि: {e}")
        if uploaded_pdf_file and hasattr(uploaded_pdf_file, 'name') and uploaded_pdf_file.name:
            try:
                gemini_client.files.delete(name=uploaded_pdf_file.name)
            except Exception:
                pass
        raise

    raw_html_from_gemini = ""
    if uploaded_pdf_file and uploaded_pdf_file.state.name == "ACTIVE":
        print("\n--- चरण 3: Gemini का उपयोग करके PDF से HTML जेनरेट करना ---")
        raw_html_from_gemini = generate_html_from_pdf_gemini_direct_img(
            gemini_client,
            text_model_name,
            uploaded_pdf_file,
            images_metadata,
            target_languages_param
        )
    else:
        message = "HTML जनरेशन छोड़ा जा रहा है क्योंकि PDF सक्रिय नहीं है या अपलोड विफल हो गया है।"
        print(message)
        head_content_for_error = f"<meta charset=\"UTF-8\"><title>त्रुटि</title>"
        raw_html_from_gemini = f"<html><head>{head_content_for_error}</head><body><h1>PDF प्रसंस्करण विफल</h1><p>AI मॉडल द्वारा PDF फ़ाइल को संसाधित नहीं किया जा सका।</p></body></html>"

    print("\n--- चरण 4: HTML को अंतिम रूप देना ---")
    final_html_content = finalize_html(raw_html_from_gemini, target_languages_param)

    with open(final_html_file_path, "w", encoding="utf-8") as f:
        f.write(final_html_content)
    print(f"\n--- प्रक्रिया पूर्ण ---")
    print(f"अंतिम HTML यहाँ सहेजा गया: {final_html_file_path}")
    print(f"निकाली गई छवियाँ (यदि कोई हो) यहाँ हैं: {extracted_images_folder}")

    if uploaded_pdf_file and hasattr(uploaded_pdf_file, 'name') and uploaded_pdf_file.name:
        try:
            print(f"अंतिम सफाई: Gemini से अपलोड की गई PDF '{uploaded_pdf_file.name}' को हटाया जा रहा है...")
            gemini_client.files.delete(name=uploaded_pdf_file.name)
            print("अपलोड की गई PDF सफलतापूर्वक हटाई गई।")
        except Exception as e_del:
            print(f"Gemini से अपलोड की गई PDF '{uploaded_pdf_file.name}' को अंतिम रूप से हटाने के दौरान त्रुटि: {e_del}")

    return final_html_file_path, extracted_images_folder

if __name__ == "__main__":
    # यह सुनिश्चित करने के लिए कि BytesIO Image.open के साथ काम करता है
    from io import BytesIO
    test_api_key = os.environ.get("GEMINI_API_KEY_TEST")
    if not test_api_key:
        print("स्थानीय परीक्षण के लिए कृपया GEMINI_API_KEY_TEST एनवायरनमेंट वेरिएबल सेट करें।")
    else:
        pdf_to_test = "sample.pdf"
        if not os.path.exists(pdf_to_test):
            print(f"परीक्षण PDF {pdf_to_test} नहीं मिला। एक डमी बनाया जा रहा है।")
            from reportlab.pdfgen import canvas
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.pdfbase import pdfmetrics
            
            try:
                # आपको NotoSansDevanagari-Regular.ttf फ़ाइल डाउनलोड करनी होगी और उसे स्क्रिप्ट के साथ रखना होगा
                # या सही पथ प्रदान करना होगा।
                font_path = "NotoSansDevanagari-Regular.ttf" 
                if os.path.exists(font_path):
                     pdfmetrics.registerFont(TTFont('NotoSansDevanagari', font_path))
                     hindi_font_available = True
                else:
                     print(f"हिंदी फ़ॉन्ट ({font_path}) नहीं मिला।")
                     hindi_font_available = False
            except Exception as font_e:
                print(f"हिंदी फ़ॉन्ट लोड करने में त्रुटि: {font_e}")
                hindi_font_available = False

            c = canvas.Canvas(pdf_to_test)
            c.drawString(100, 750, "Hello World. This is a test PDF.")
            if hindi_font_available:
                c.setFont("NotoSansDevanagari", 12)
            c.drawString(100, 730, "नमस्ते दुनिया। यह एक परीक्षण पीडीएफ है।")
            # एक साधारण तालिका जोड़ें
            c.drawString(100, 650, "Table Example:")
            data = [['Col1', 'Col2', 'Col3'], ['1', '2', '3'], ['एक', 'दो', 'तीन']]
            from reportlab.platypus import Table
            table = Table(data)
            table.wrapOn(c, 500, 50) # canvan, width, height
            table.drawOn(c, 100, 550)

            c.save()

        temp_output_dir = "temp_pdf_to_html_output_hindi_logic_test"
        if os.path.exists(temp_output_dir):
            shutil.rmtree(temp_output_dir)
        os.makedirs(temp_output_dir)

        try:
            html_path, img_dir = run_conversion(
                gemini_api_key_param=test_api_key,
                pdf_file_path_param=pdf_to_test,
                base_output_folder_param=temp_output_dir,
                target_languages_param=["English", "Hindi"]
            )
            print(f"स्थानीय परीक्षण सफल। HTML: {html_path}, छवियाँ: {img_dir}")
        except Exception as e:
            print(f"स्थानीय परीक्षण विफल: {e}")
            import traceback
            traceback.print_exc()
