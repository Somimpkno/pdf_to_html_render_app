# PDF to HTML Converter (using Gemini API)

This is a Flask web application that allows users to upload a PDF file, provide their Gemini API key, and select target languages for translation. The application then converts the PDF content into an HTML file, preserving formatting and images, and provides translations as requested.

## Features

*   Upload PDF files.
*   Provide Gemini API Key for processing.
*   Select multiple target languages for text content.
*   Extracts images from the PDF and includes them in the HTML.
*   Generates alt text for images (optional, can be slow).
*   Preserves general PDF formatting like headings, lists, and tables.
*   Handles MathJax for equations.
*   Outputs a ZIP file containing the HTML and extracted images.

## How to use on Render

1.  Deploy this repository to Render.com as a Web Service.
2.  Open the provided Render URL.
3.  Enter your Gemini API Key.
4.  Upload your PDF file.
5.  Select the desired output language(s).
6.  Click "Convert PDF to HTML".
7.  Download the resulting ZIP file.

## Project Structure

*   `app.py`: The main Flask application file.
*   `converter_logic.py`: Contains the core logic for PDF processing and Gemini API interaction.
*   `requirements.txt`: Lists the Python dependencies.
*   `.gitignore`: Specifies intentionally untracked files that Git should ignore.
*   `LICENSE`: (If you added one) Contains the license terms for the project.
