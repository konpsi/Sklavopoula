"""Questionnaire outline for the voice-guided CV interview."""

QUESTIONNAIRE = (
    {
        "id": "full_name",
        "title": "Full name",
        "question": "What name would you like to appear at the top of your CV?",
    },
    {
        "id": "professional_title",
        "title": "Professional title",
        "question": "What professional title or type of role best describes you?",
    },
    {
        "id": "contact_details",
        "title": "Contact details",
        "question": "Which contact details and professional links should your CV include?",
    },
    {
        "id": "location",
        "title": "Location",
        "question": "Where are you based, and are you open to remote work or relocation?",
    },
    {
        "id": "career_goal",
        "title": "Career goal",
        "question": "What kind of role are you looking for, and what would you like to do next?",
    },
    {
        "id": "work_experience",
        "title": "Work experience",
        "question": "Walk me through your most relevant work experience, including employers, roles, and dates.",
    },
    {
        "id": "achievements",
        "title": "Key achievements",
        "question": "What measurable achievements or moments from your work are you most proud of?",
    },
    {
        "id": "education",
        "title": "Education",
        "question": "Tell me about your education, including qualifications, institutions, and dates.",
    },
    {
        "id": "skills",
        "title": "Skills",
        "question": "Which technical, practical, and interpersonal skills should stand out on your CV?",
    },
    {
        "id": "projects",
        "title": "Projects",
        "question": "Which projects best show what you can do, and what was your contribution?",
    },
    {
        "id": "certifications_languages",
        "title": "Certifications and languages",
        "question": "Do you have any relevant certifications, courses, awards, or language skills?",
    },
    {
        "id": "additional_information",
        "title": "Additional information",
        "question": "Is there anything else you want an employer to know about you?",
    },
)


QUESTION_BY_ID = {item["id"]: item for item in QUESTIONNAIRE}
