# Meeting Summary Bot

Flask web application that turns long meeting transcripts into concise summaries and action items using Google's Gemini models.

## Features

- Paste meeting transcripts and optional notes, then receive structured summaries.
- Maintains recent chat context for follow-up questions or refinements.
- Uses `google-generativeai` with configurable model name (defaults to `gemini-1.5-flash`).

## Requirements

- Python 3.10+
- Google Gemini API key
- MySQL Server 5.7+ or 8.0+

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Set up MySQL database:

   - Install MySQL Server if not already installed
   - Create a database for storing meeting summaries:
   
   ```sql
   CREATE DATABASE meeting_summaries;
   ```

3. Set your environment variables:

   ```powershell
   # Required: Gemini API key
   setx GEMINI_API_KEY "<your-api-key>"
   
   # Required: MySQL database credentials
   setx DB_HOST "localhost"
   setx DB_PORT "3306"
   setx DB_NAME "meeting_summaries"
   setx DB_USER "root"
   setx DB_PASSWORD "<your-mysql-password>"
   
   # Optional: Override model name
   setx GEMINI_MODEL "gemini-1.5-pro"
   ```

   Restart the shell after using `setx`, or export the variables in the current session instead:

   ```powershell
   $env:GEMINI_API_KEY = "<your-api-key>"
   $env:DB_HOST = "localhost"
   $env:DB_PORT = "3306"
   $env:DB_NAME = "meeting_summaries"
   $env:DB_USER = "root"
   $env:DB_PASSWORD = "<your-mysql-password>"
   $env:GEMINI_MODEL = "gemini-2.5-flash"
   
   # Optional: SMTP configuration for email functionality
   $env:SMTP_HOST = "smtp.gmail.com"
   $env:SMTP_PORT = "587"
   $env:SMTP_USER = "<your-email@gmail.com>"
   $env:SMTP_PASSWORD = "<your-app-password>"
   $env:SMTP_FROM_EMAIL = "<your-email@gmail.com>"
   $env:SMTP_USE_TLS = "true"
   ```

4. Run the Flask development server:

   ```bash
   flask --app app run --reload
   ```

   The app will be available at http://127.0.0.1:5000.

## Environment Variables

| Name             | Description                                         | Required | Default            |
| ---------------- | --------------------------------------------------- | -------- | ------------------ |
| `GEMINI_API_KEY` | Google Gemini API key                               | Yes      | —                  |
| `GEMINI_MODEL`   | Model to use for summarization                      | No       | `gemini-2.5-flash` |
| `DB_HOST`        | MySQL server host                                   | No       | `localhost`        |
| `DB_PORT`        | MySQL server port                                   | No       | `3306`             |
| `DB_NAME`        | MySQL database name                                  | No       | `meeting_summaries`|
| `DB_USER`        | MySQL username                                      | No       | `root`             |
| `DB_PASSWORD`    | MySQL password                                      | No       | ``                 |
| `SMTP_HOST`      | SMTP server host (e.g., smtp.gmail.com)             | No*      | —                  |
| `SMTP_PORT`      | SMTP server port                                    | No*      | `587`              |
| `SMTP_USER`      | SMTP username/email                                 | No*      | —                  |
| `SMTP_PASSWORD`  | SMTP password or app password                       | No*      | —                  |
| `SMTP_FROM_EMAIL`| Email address to send from                          | No*      | `SMTP_USER` value  |
| `SMTP_USE_TLS`   | Use TLS encryption (true/false)                     | No       | `true`             |

\* Required only if you want to use email functionality

## Database Schema

The application automatically creates a `meeting_summaries` table with the following structure:

- `id` (INT, AUTO_INCREMENT, PRIMARY KEY)
- `input` (TEXT) - The original meeting transcript
- `summary` (TEXT) - Parsed summary section
- `key_decisions` (TEXT) - Parsed key decisions section
- `action_items` (TEXT) - Parsed action items section
- `created_at` (TIMESTAMP) - Timestamp of when the record was created

## Email Configuration

The application supports sending meeting summaries via email. To enable this feature:

1. **For Gmail:**
   - Enable 2-Factor Authentication
   - Generate an App Password: https://myaccount.google.com/apppasswords
   - Use the app password as `SMTP_PASSWORD`

2. **For other email providers:**
   - **Outlook/Hotmail:** `smtp-mail.outlook.com`, port `587`
   - **Yahoo:** `smtp.mail.yahoo.com`, port `587`
   - **Custom SMTP:** Use your provider's SMTP settings

3. **Example configuration:**
   ```powershell
   $env:SMTP_HOST = "smtp.gmail.com"
   $env:SMTP_PORT = "587"
   $env:SMTP_USER = "your-email@gmail.com"
   $env:SMTP_PASSWORD = "your-app-password"
   $env:SMTP_FROM_EMAIL = "your-email@gmail.com"
   $env:SMTP_USE_TLS = "true"
   ```

## Notes

- The frontend keeps the 10 most recent turns of history for better follow-up summaries.
- Responses are returned as Markdown and displayed in separate sections (Summary, Key Decisions, Action Items) with clean formatting.
- All meeting transcripts and their parsed summaries are automatically saved to the MySQL database.
- If the database connection fails, the application will continue to work but won't save data (warnings will be printed to the console).
- Email functionality is optional. If SMTP is not configured, the app will work normally but won't send emails.
- Users can optionally provide an email address in the UI to receive the summary via email.

