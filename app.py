import os
import smtplib
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import google.generativeai as genai
import mysql.connector
from mysql.connector import Error
from mysql.connector.cursor import MySQLCursorDict


load_dotenv()

app = Flask(__name__)

SYSTEM_INSTRUCTION = (
    "You are MeetSummary, an AI assistant that summarizes business meetings. "
    "Produce concise, business-ready outputs that capture key points, decisions, and action items. "
    "Always format your response in Markdown with three sections in this exact order: "
    "1) A heading 'Summary' followed by bullet points, "
    "2) A heading 'Key Decisions' followed by bullet points (write 'None noted.' if there are no decisions), "
    "3) A heading 'Action Items' followed by bullet points including owners and due dates when available "
    "('Owner: <role or name>' when unspecified). "
    "Keep language clear and professional."
)


def configure_gemini() -> genai.GenerativeModel:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing GEMINI_API_KEY environment variable. "
            "Set it before starting the Flask app."
        )

    genai.configure(api_key=api_key)

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return genai.GenerativeModel(
        model_name,
        system_instruction=SYSTEM_INSTRUCTION,
    )


model = None


def get_db_connection() -> Optional[mysql.connector.MySQLConnection]:
    """Create and return a MySQL database connection."""
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            database=os.getenv("DB_NAME", "meeting_summaries"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None


def create_table_if_not_exists() -> None:
    """Create the meeting_summaries table if it doesn't exist."""
    connection = get_db_connection()
    if not connection:
        print("Warning: Could not connect to database. Table creation skipped.")
        return

    try:
        cursor = connection.cursor()
        create_table_query = """
        CREATE TABLE IF NOT EXISTS meeting_summaries (
            id INT AUTO_INCREMENT PRIMARY KEY,
            input TEXT NOT NULL,
            summary TEXT,
            key_decisions TEXT,
            action_items TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        cursor.execute(create_table_query)
        connection.commit()
        print("Table 'meeting_summaries' is ready.")
    except Error as e:
        print(f"Error creating table: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def parse_response_sections(reply: str) -> Tuple[str, str, str]:
    """
    Parse the markdown response into separate sections.
    Returns: (summary, key_decisions, action_items)
    """
    sections = {
        "summary": [],
        "key_decisions": [],
        "action_items": []
    }
    
    # Handle None or empty reply
    if not reply:
        return None, None, None
    
    lines = reply.split('\n')
    current_section = None
    
    for line in lines:
        # Skip None lines
        if line is None:
            continue
        
        original_line = line
        line = line.strip() if line else ""
        
        # Skip empty lines but don't reset current_section
        if not line:
            continue
        
        # Check for section headers (more specific matching)
        line_lower = line.lower()
        
        # Remove # symbols and check for section names
        header_text = line_lower.lstrip('#').strip()
        
        if header_text == 'summary':
            current_section = "summary"
            continue
        elif 'key' in header_text and 'decision' in header_text:
            current_section = "key_decisions"
            continue
        elif header_text.startswith('action'):
            # Match "action items", "action item", "actions", etc.
            # This is more flexible and catches all action-related headers
            current_section = "action_items"
            continue
        elif line.startswith('#'):
            # If we hit another header we don't recognize, reset current_section
            current_section = None
            continue
        
        # Only process content if we're in a recognized section
        if not current_section:
            continue
        
        # Handle bullet points (various formats) - check this first
        if line and (line.startswith('-') or line.startswith('*') or line.startswith('•')):
            content = line.lstrip('-*•').strip()
            if content and content.lower() not in ['none noted.', 'none.', 'n/a', 'na', 'none']:
                sections[current_section].append(content)
        # Handle numbered lists
        elif line and len(line) > 0 and line[0].isdigit() and '.' in line[:3]:
            # Extract content after number and period
            parts = line.split('.', 1)
            if len(parts) == 2:
                content = parts[1].strip() if parts[1] else ""
                if content and content.lower() not in ['none noted.', 'none.', 'n/a', 'na', 'none']:
                    sections[current_section].append(content)
        # Handle continuation lines (non-bullet, non-header lines)
        # Only process if we already have items in this section
        elif current_section and sections[current_section]:
            # Only append as continuation if the last item doesn't end with punctuation
            last_item = sections[current_section][-1]
            if last_item and not last_item.rstrip().endswith(('.', '!', '?', ':')):
                sections[current_section][-1] += " " + line
            else:
                # New item without bullet marker - only add if it's not empty and not "none"
                if line and line.lower() not in ['none noted.', 'none.', 'n/a', 'na', 'none']:
                    sections[current_section].append(line)
        # First item in section without bullet marker
        elif current_section:
            if line and line.lower() not in ['none noted.', 'none.', 'n/a', 'na', 'none']:
                sections[current_section].append(line)
    
    # Join each section with newlines
    summary_text = '\n'.join(sections["summary"]) if sections["summary"] else None
    key_decisions_text = '\n'.join(sections["key_decisions"]) if sections["key_decisions"] else None
    action_items_text = '\n'.join(sections["action_items"]) if sections["action_items"] else None
    
    return summary_text, key_decisions_text, action_items_text


def send_email_summary(
    recipient_email: str,
    transcript: str,
    summary: Optional[str],
    key_decisions: Optional[str],
    action_items: Optional[str],
) -> bool:
    """Send meeting summary via email using SMTP."""
    try:
        # Get SMTP configuration from environment variables
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")
        smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)
        
        if not all([smtp_host, smtp_user, smtp_password]):
            print("Warning: SMTP configuration incomplete. Email not sent.")
            return False
        
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Meeting Summary"
        msg["From"] = smtp_from_email
        msg["To"] = recipient_email
        
        # Create email body
        transcript_safe = transcript or ""
        transcript_preview = transcript_safe[:500] + ('...' if len(transcript_safe) > 500 else '')
        
        body_text = f"""Meeting Summary

Original Transcript:
{transcript_preview}

"""
        
        if summary:
            body_text += f"Summary:\n{summary}\n\n"
        
        if key_decisions:
            body_text += f"Key Decisions:\n{key_decisions}\n\n"
        
        if action_items:
            body_text += f"Action Items:\n{action_items}\n\n"
        
        # Create HTML version with escaped content
        transcript_escaped = html.escape(transcript_preview)
        body_html = f"""
        <html>
          <head></head>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #2563eb;">Meeting Summary</h2>
            
            <h3 style="color: #172554; border-bottom: 2px solid #2563eb; padding-bottom: 8px;">Original Transcript</h3>
            <pre style="background: #f1f5f9; padding: 12px; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word;">{transcript_escaped}</pre>
        """
        
        if summary:
            summary_escaped = html.escape(summary)
            body_html += f"""
            <h3 style="color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-top: 24px;">Summary</h3>
            <pre style="background: #f1f5f9; padding: 12px; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word;">{summary_escaped}</pre>
            """
        
        if key_decisions:
            decisions_escaped = html.escape(key_decisions)
            body_html += f"""
            <h3 style="color: #059669; border-bottom: 2px solid #059669; padding-bottom: 8px; margin-top: 24px;">Key Decisions</h3>
            <pre style="background: #f1f5f9; padding: 12px; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word;">{decisions_escaped}</pre>
            """
        
        if action_items:
            action_escaped = html.escape(action_items)
            body_html += f"""
            <h3 style="color: #dc2626; border-bottom: 2px solid #dc2626; padding-bottom: 8px; margin-top: 24px;">Action Items</h3>
            <pre style="background: #f1f5f9; padding: 12px; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word;">{action_escaped}</pre>
            """
        
        body_html += """
          </body>
        </html>
        """
        
        # Attach both plain text and HTML versions
        part1 = MIMEText(body_text, "plain")
        part2 = MIMEText(body_html, "html")
        
        msg.attach(part1)
        msg.attach(part2)
        
        # Connect to SMTP server and send email
        use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        
        if smtp_port == 465:
            # SSL connection for port 465
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            # TLS connection for port 587
            server = smtplib.SMTP(smtp_host, smtp_port)
            if use_tls:
                server.starttls()
        
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        
        print(f"Successfully sent email to {recipient_email}")
        return True
        
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def save_to_database(input_text: str, summary: Optional[str], key_decisions: Optional[str], action_items: Optional[str]) -> bool:
    """Save the meeting summary data to MySQL database."""
    connection = get_db_connection()
    if not connection:
        print("Warning: Could not connect to database. Data not saved.")
        return False
    
    try:
        cursor = connection.cursor()
        insert_query = """
        INSERT INTO meeting_summaries (input, summary, key_decisions, action_items)
        VALUES (%s, %s, %s, %s)
        """
        cursor.execute(insert_query, (input_text, summary, key_decisions, action_items))
        connection.commit()
        print(f"Successfully saved meeting summary to database (ID: {cursor.lastrowid})")
        return True
    except Error as e:
        print(f"Error saving to database: {e}")
        connection.rollback()
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


@app.route("/")
def index() -> str:
    return render_template("index.html")


def build_prompt(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    transcript = payload.get("transcript", "").strip()
    # Directives are hardcoded to empty string since the UI does not provide an input field for them.
    directives = "" 
    history = payload.get("history", [])

    chat_history = []
    for entry in history:
        role = entry.get("role")
        content = entry.get("content", "")
        if role not in {"user", "assistant", "model"}:
            continue
        normalized_role = "user" if role == "user" else "model"
        chat_history.append({"role": normalized_role, "parts": [content]})

    user_prompt = (
        "Meeting transcript:\n"
        f"{transcript if transcript else 'No transcript provided.'}\n\n"
        "Additional directives or questions:\n"
        f"{directives if directives else 'None.'}"
    )

    contents = list(chat_history)
    contents.append({"role": "user", "parts": [user_prompt]})

    return contents


@app.route("/api/chat", methods=["POST"])
def chat() -> Any:
    global model
    payload: Dict[str, Any] = request.get_json() or {}

    try:
        if model is None:
            model = configure_gemini()

        contents = build_prompt(payload)

        response = model.generate_content(
            contents,
            generation_config={
                "temperature": 0.4,
                "top_p": 0.9,
                "top_k": 40,
                "max_output_tokens": 1024,
            },
        )

        if not response.candidates:
            raise ValueError("Gemini returned no candidates")

        candidate = next(
            (
                cand
                for cand in response.candidates
                if cand.content and getattr(cand.content, "parts", None)
            ),
            None,
        )

        if not candidate:
            raise ValueError("Gemini returned empty content")

        reply_parts = []
        for part in candidate.content.parts:
            text = getattr(part, "text", None)
            if text:
                reply_parts.append(text)

        if not reply_parts:
            raise ValueError("Gemini returned no text in the response")

        reply = "\n".join(reply_parts).strip() if reply_parts else ""

        # Parse the response into separate sections
        transcript = payload.get("transcript", "").strip() if payload.get("transcript") else ""
        email = payload.get("email", "").strip() if payload.get("email") else ""
        summary, key_decisions, action_items = parse_response_sections(reply)
        
        # Save to database
        if transcript:
            save_to_database(transcript, summary, key_decisions, action_items)
        
        # Send email if provided
        email_sent = False
        if email:
            email_sent = send_email_summary(
                email, transcript, summary, key_decisions, action_items
            )

        return jsonify({
            "reply": reply,
            "email_sent": email_sent
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/recent-meetings", methods=["GET"])
def get_recent_meetings() -> Any:
    """Fetch recent meetings from the database."""
    try:
        limit = request.args.get("limit", default=10, type=int)
        connection = get_db_connection()
        
        if not connection:
            return jsonify({"error": "Database connection failed"}), 500
        
        try:
            cursor = connection.cursor(cursor_class=MySQLCursorDict)
            query = """
            SELECT id, input, summary, key_decisions, action_items, created_at
            FROM meeting_summaries
            ORDER BY created_at DESC
            LIMIT %s
            """
            cursor.execute(query, (limit,))
            meetings = cursor.fetchall()
            
            # Format the data for JSON response
            result = []
            for meeting in meetings:
                result.append({
                    "id": meeting["id"],
                    "input": meeting["input"],
                    "summary": meeting["summary"],
                    "key_decisions": meeting["key_decisions"],
                    "action_items": meeting["action_items"],
                    "created_at": meeting["created_at"].isoformat() if meeting["created_at"] else None
                })
            
            return jsonify({"meetings": result})
        except Error as e:
            return jsonify({"error": f"Database error: {str(e)}"}), 500
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    # Create database table on startup
    create_table_if_not_exists()
    app.run(debug=True)