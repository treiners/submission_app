import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_confirmation_email(gmail_address, gmail_app_password, from_name,
                             to_address, name, student_id, code, filenames,
                             assignment_title, declared_labels=None):
    if not (gmail_address and gmail_app_password):
        raise RuntimeError("Gmail credentials are not configured (see .env.example).")

    declared_labels = declared_labels or []

    subject = f"Submission received: {assignment_title}"
    file_list = "\n".join(f"  - {f}" for f in filenames) if filenames else "  (none)"
    body = (
        f"Hi {name},\n\n"
        f"Your submission for '{assignment_title}' has been received.\n\n"
        f"Student ID: {student_id}\n"
        f"Confirmation code: {code}\n"
        f"Files submitted:\n{file_list}\n"
    )
    if declared_labels:
        declared_list = "\n".join(f"  - {label}" for label in declared_labels)
        body += f"\nDeclared as not submitted:\n{declared_list}\n"
    body += (
        f"\nPlease keep this code as proof of submission.\n\n"
        f"This is an automated message, please do not reply.\n"
    )

    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{gmail_address}>"
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, [to_address], msg.as_string())
