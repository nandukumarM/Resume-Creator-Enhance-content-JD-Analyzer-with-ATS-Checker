from app import generate_brand_new_pdf, app
import io

def test_mapping_and_generation():
    # Sample "Generic" data (as produced by AI)
    generic_data = {
        'personal_info': {
            'name': 'Test User',
            'contact_info': 'test@example.com | 123-456-7890 | Bangalore'
        },
        'summary': 'Experienced professional seeking bank role.',
        'skills': {
            'technical': ['Python', 'Flask'],
            'soft': ['Communication', 'Leadership']
        },
        'experience': [
            {
                'title': 'Developer',
                'company': 'Tech Corp',
                'dates': '2020-Present',
                'bullets': ['Developed app', 'Fixed bugs']
            }
        ],
        'education': [
            {
                'degree': 'B.Tech',
                'school': 'University',
                'dates': '2016-2020'
            }
        ]
    }

    # Simulate Flask app context for render_template
    with app.app_context():
        try:
            pdf_buffer = generate_brand_new_pdf(generic_data, template_name='bank')
            
            # Save to file to manually inspect if needed
            with open('test_mapped_bank_resume.pdf', 'wb') as f:
                f.write(pdf_buffer.getvalue())
                
            print("SUCCESS: Bank PDF generated from mapped data.")
        except Exception as e:
            print(f"FAILURE: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_mapping_and_generation()
