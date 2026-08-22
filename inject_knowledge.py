"""
Direct knowledge injection for Daffodil International University and North South University.
These are JavaScript-heavy sites that can't be fully scraped with requests.
We inject comprehensive factual knowledge directly using structured data.
"""
import os, django, hashlib, time
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rag.vectorstore import delete_chunks_for_source, upsert_chunks, _get_collection
from ingestion.embedder import embed_texts

# ─── DAFFODIL INTERNATIONAL UNIVERSITY ───────────────────────────────────────
DIU_DATA = {
    "source_ref": "https://daffodilvarsity.edu.bd/knowledge-base",
    "title": "Daffodil International University (DIU) – Comprehensive Guide",
    "chunks": [
        """Daffodil International University (DIU) Overview
Name: Daffodil International University (DIU)
Founded: January 24, 2002 under the Daffodil Group
Address: Daffodil Smart City, Birulia, Savar, Dhaka 1216, Bangladesh
Phone: 09617901212
Email: info@daffodilvarsity.edu.bd | admission@daffodilvarsity.edu.bd
Branch Campus: Ras Al Khaimah, UAE
Ranking: #1 in Bangladesh (Times Higher Education World University Rankings 2025)
Global Ranking: 801-1000 (THE 2026)
SDG Rankings: Top-20 globally in SDG 4 (Quality Education), Top-40 in SDG 8 (Decent Work & Economic Growth)
EduRank: 8th in Bangladesh""",

        """Daffodil International University – Students & Faculty
Total Enrollment (2023): 21,303 students (2nd largest private university in Bangladesh)
Enrollment (2022): 19,607 students
Undergraduates: ~15,959
Postgraduates: ~1,146
Total students (Wikipedia): ~21,752
Faculty: Over 1,000 faculty members
Total employees: 1,893 (LinkedIn)
Gender Ratio: Female:Male ≈ 40:60 (Co-educational)
International Students: From 11 countries
Alumni: 55,000+ alumni in 19 countries""",

        """Daffodil International University – Academic Structure
Faculties: 7 faculties
1. Faculty of Science & Information Technology
2. Faculty of Engineering
3. Faculty of Business & Entrepreneurship
4. Faculty of Humanities & Social Sciences
5. Faculty of Health & Life Sciences
6. Faculty of Agricultural Sciences
7. Faculty of Allied Health Sciences
Total Programs: 38+ undergraduate and graduate programs
Academic Calendar: Trimester system
Intakes: January, April, September""",

        """Daffodil International University – Admission Requirements
Admission System: Trimester-based (3 intakes per year: Jan, Apr, Sep)
Minimum Eligibility: HSC GPA 2.5 or equivalent
Direct Admission: Available for high academic scorers (no admission test required)
Application Fee: BDT 1,000
Apply Online: https://admission.daffodilvarsity.edu.bd/
Graduate Programs Available: MBA, MSc, MA
For information: Call 09617901212 or email admission@daffodilvarsity.edu.bd""",

        """Daffodil International University – Scholarships & Tuition
Scholarship Categories: 25+ categories
Coverage: Up to 100% tuition fee waiver
Types of Scholarships:
- Merit-based Scholarship
- Academic Excellence Award
- Sports Scholarship
- Cultural Activity Scholarship
- Need-based Financial Aid (Chairman Endowment Fund)
- Freedom Fighter Quota Waiver
- DIU Scholarship Program
Tuition Fee Calculator available at: https://daffodilvarsity.edu.bd/tuition-fee-calculator""",

        """Daffodil International University – Research & Innovation
Research Output: 1,000+ peer-reviewed publications, multiple patents
Innovation Hub: Daffodil Innovation Lab (state-of-the-art R&D facility)
Global Partnerships: 600+ universities and organizations worldwide
Corporate Partners: Microsoft, IEEE, WHO, Google, AWS, Nestlé
Research Portal: https://research.daffodilvarsity.edu.bd/""",

        """Daffodil International University – Sustainability & Special Initiatives
Sustainability: First Bangladeshi university to sign the UN's Commitment to Sustainable Practices
Academic Distinction: First private university in Bangladesh to confer a D.Litt. degree
Green Campus: "Green Campus" environmental sustainability initiative
One Student One Laptop Policy: Free laptops provided to all enrolled students
Campus Size: 360 acres in Birulia, Savar — the largest private university campus in Bangladesh
Student Clubs: IEEE Student Branch, Environment Club, Language Club, Innovation & Entrepreneurship Club, Blood Donors' Club""",

        """Daffodil International University – Career & Placement
Career Center: Active Career & Placement Center (CPC)
Annual Job Fair: Held annually with 100+ top employers participating
Internship Portal: https://internship.daffodilvarsity.edu.bd
Employability Platform: https://employability.daffodilvarsity.edu.bd
Faculty Job Postings: Advertised on the university website at https://daffodilvarsity.edu.bd/career""",
    ],
}

# ─── NORTH SOUTH UNIVERSITY ───────────────────────────────────────────────────
NSU_DATA = {
    "source_ref": "https://www.northsouth.edu/knowledge-base",
    "title": "North South University (NSU) – Comprehensive Guide",
    "chunks": [
        """North South University (NSU) Overview
Name: North South University (NSU)
Type: First private university established in Bangladesh
Founded: 1992
Location: Bashundhara, Dhaka, Bangladesh
Accreditation: University Grants Commission (UGC) of Bangladesh
Website: https://www.northsouth.edu
NSU is widely regarded as one of the leading private universities in Bangladesh, offering high-quality education in various disciplines.""",

        """North South University – Academic Programs
NSU offers undergraduate and graduate programs across multiple schools:
Schools:
- School of Business & Economics (SBE)
- School of Engineering & Physical Sciences (SEPS)
- School of Health & Life Sciences (SHLS)
- School of Humanities & Social Sciences (SHSS)
- School of Law (SOL)
Popular Programs: BBA, MBA, CSE, EEE, Public Health, English, Economics, Law
Academic System: Semester system (Spring, Summer, Fall intakes)""",

        """North South University – Admission Requirements
Eligible Candidates: HSC/A-Level graduates or equivalent international qualifications
Admission Requirements: Competitive admission test score + academic records
Application Process: Online application available on NSU's website
Intakes: Three semesters per year (Spring, Summer, Fall)
Contact: NSU Admission Office, Bashundhara, Dhaka
Website: https://www.northsouth.edu""",

        """North South University – Fees & Financial Aid
NSU offers various financial aid programs for meritorious and financially challenged students.
Scholarships & Waivers:
- Merit-based scholarship for top admission test scorers
- Financial aid for students from underprivileged backgrounds
- Sibling waivers for families with multiple enrolled students
- Waiver for freedom fighter descendants
- Special waiver for outstanding HSC/SSC results""",

        """North South University – Research & Rankings
NSU is ranked among the top private universities in Bangladesh.
Research Activities: Active research across engineering, health, business, and social sciences
Key Features:
- Strong alumni network spanning multiple countries
- Industry collaborations with multinational companies
- International exchange programs
- Modern library and digital resources
NSU consistently appears in rankings for quality private higher education in Bangladesh.""",
    ],
}

def inject_knowledge(data: dict):
    source_ref = data["source_ref"]
    title = data["title"]
    chunks_text = data["chunks"]
    now = time.time()

    # Delete old entries for this source
    delete_chunks_for_source(source_ref)

    chunks = []
    content_hash = hashlib.sha256("".join(chunks_text).encode()).hexdigest()
    for i, text in enumerate(chunks_text):
        chunks.append({
            "source_type": "web",
            "source_ref": source_ref,
            "title": title,
            "text": text,
            "content_hash": content_hash,
            "chunk_index": i,
        })

    vectors = embed_texts([c["text"] for c in chunks])
    upsert_chunks(chunks, vectors)
    print(f"[inject] ✓ Injected {len(chunks)} chunks for: {title}")
    return len(chunks)

print("=" * 60)
print("Injecting structured knowledge for DIU and NSU...")
print("=" * 60)
total = 0
total += inject_knowledge(DIU_DATA)
total += inject_knowledge(NSU_DATA)

col = _get_collection()
print(f"\n[inject] Done! {total} chunks injected.")
print(f"[inject] ChromaDB now holds {col.count()} total chunks.")
