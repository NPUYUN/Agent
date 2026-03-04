
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

def create_problematic_pdf(filepath):
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    # 1. Heading Hierarchy Error (H1 -> H3, skipping H2)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, height - 2 * cm, "1. Introduction")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, height - 3 * cm, "1.1.1 Sub-subsection (Skipped 1.1)")
    
    # 2. Typo in Critical Keyword
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 4 * cm, "We use TesnorFlow for implementation.") # Typo: TensorFlow
    
    # 3. Mixed Punctuation (Skipped due to font issues in synthetic generation)
    # c.setFont("SimSun", 10) 
    # c.drawString(2 * cm, height - 5 * cm, "This is a test sentence。") 
    
    # 4. Citation Error (Citation after punctuation)
    c.drawString(2 * cm, height - 6 * cm, "Previous work shows this.[1]") # Error: .[1]
    
    # 5. Figure Caption Position Error (Caption at top for Figure)
    c.drawString(2 * cm, height - 8 * cm, "Fig. 1: Architecture Diagram")
    c.rect(2 * cm, height - 12 * cm, 10 * cm, 3.5 * cm) # The figure box
    
    # 6. Terminology Inconsistency
    c.drawString(2 * cm, height - 13 * cm, "Deep Learning is powerful.")
    c.drawString(2 * cm, height - 13.5 * cm, "We verify deep-learning models.") # Inconsistent
    
    c.save()
    print(f"Created {filepath}")

if __name__ == "__main__":
    output_dir = "tests/data"
    os.makedirs(output_dir, exist_ok=True)
    create_problematic_pdf(os.path.join(output_dir, "problematic.pdf"))
