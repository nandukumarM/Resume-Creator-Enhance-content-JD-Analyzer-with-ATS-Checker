from xhtml2pdf import pisa
import io

def test_pdf_gen():
    html_content = "<html><body><h1>Hello ATS</h1></body></html>"
    buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=buffer)
    
    if pisa_status.err:
        print("PDF generation failed")
    else:
        print("PDF generation successful")

if __name__ == "__main__":
    test_pdf_gen()
