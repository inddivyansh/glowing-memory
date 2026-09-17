# Indian Army PR Monitor & Automated Fact-Check Bot

An automated public relations and factual-accuracy monitoring system for Instagram. The tool tracks designated public hashtags related to the Indian Army, uses a local Large Language Model (via Ollama) to identify checkable factual claims and misinformation, automatically posts official clarification comments, and maintains an audit log of all interactions.

---

## What This Project Does

```
                     +---------------------------------------+
                     |        Target Instagram Hashtags      |
                     |  (#indianarmy, #indianarmedforces...) |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Fetch Recent Media & Filter User   |
                     |   (Follower count, business account)  |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Ollama Local LLM Caption Triage    |
                     |  - Checkable factual claim detection  |
                     |  - High confidence verification (>0.7)|
                     |  - Generates concise official reply   |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |      Post Comment to Instagram        |
                     |    `client.media_comment(media_id)`   |
                     |   Human-like random delay (60-180s)   |
                     +-------------------+-------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Audit Log Entry (`audit_log.csv`)  |
                     |  - Media ID, Author, Link, Caption    |
                     |  - Detected issue & confidence score  |
                     |  - Comment text & execution status    |
                     +---------------------------------------+
```

1. **Hashtag Monitoring**: Continuously or periodically monitors designated hashtags using `instagrapi`.
2. **Account Profiling & Filtering**: Filters candidate posts based on business account status and follower thresholds to avoid bot traps and target relevant posts.
3. **Local LLM Analysis (Ollama)**: Evaluates captions using a zero-temperature prompt. Flags fabricated operational claims, false attribution, and altered media claims while bypassing benign opinions or criticism.
4. **Automated Response**: When a high-confidence factual claim is detected, it generates an official, neutral correction linking to authorized public-information channels and comments directly on the post.
5. **Anti-Detection Pacing**: Spacings and rate limits (customizable 60–180 second delays) mimic human behavior to prevent Instagram rate-limiting or automated action blocks.
6. **Immutable Audit Trail**: All evaluated posts, detected issues, confidence ratings, and posted comments are permanently logged to `audit_log.csv` for downstream auditing and oversight.

---

## Setup Guide

### 1. Prerequisites
- **Python**: Version 3.10 or newer.
- **Ollama**: Download and install from [ollama.com](https://ollama.com/).
- **Ollama Model**: Pull your desired model (e.g. `llama3.2`):
  ```bash
  ollama run llama3.2
  ```
- **Instagram Account**: Dedicated account credentials for automated PR responses.

### 2. Environment Setup

#### Option A: Automated Setup (PowerShell on Windows)
Run the bundled setup script to automatically create the virtual environment and install all dependencies:
```powershell
.\setup.ps1
```
Then activate the environment:
```powershell
.\.venv\Scripts\Activate.ps1
```

#### Option B: Manual Setup
```bash
# Create and activate virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create your `.env` file by copying the template:
```powershell
Copy-Item .env.example .env
```

Edit `.env` with your settings:
```env
# Instagram Credentials
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password

# Target hashtags (comma-separated, without '#')
HASHTAGS=indianarmy,indianarmedforces

# Ollama local model
OLLAMA_MODEL=llama3.2

# Approved official primary source link for replies
OFFICIAL_INFORMATION_SOURCE=https://indianarmy.nic.in

# Safety & Anti-Ban Controls
MAX_COMMENTS_PER_SESSION=3
MIN_DELAY_SECONDS=60
MAX_DELAY_SECONDS=180
FOLLOWER_THRESHOLD=0
FOLLOW_BUSINESSES=True

# Mode (True = continuous daily scheduler; False = single execution)
SCHEDULE_MODE=False
```

---

## How to Use

### 1. Single Execution Run
To run a single monitoring and response session immediately:
```powershell
python army_pr_monitor.py
```
- Fetches recent posts for configured hashtags.
- Analyzes candidate captions with Ollama.
- Posts corrections on detected misinformation.
- Saves results to `audit_log.csv` and finishes.

### 2. Continuous Scheduled Mode
To run the monitor continuously with randomized daily sessions during waking hours:
```powershell
python army_pr_monitor.py --schedule
```
*(Or set `SCHEDULE_MODE=True` in `.env`).*

### 3. Monitoring & Auditing Output

- **Console & File Logs**: Real-time logging is output to the terminal and stored in `monitor.log`.
- **Audit Records**: Stored in `audit_log.csv` with the following columns:
  - `media_id`: Instagram media ID.
  - `username`: Author handle.
  - `permalink`: Direct URL to the Instagram post.
  - `caption`: Original post text.
  - `detected_issue`: Specific factual claim or issue identified by the LLM.
  - `confidence`: Confidence score (0.0 to 1.0).
  - `comment_text`: Exact text of the comment posted.
  - `status`: Execution status (`posted` or `failed: <reason>`).
  - `collected_at`: UTC timestamp of the action.

---

## What Can Be Added (Roadmap & Enhancements)

Here are high-value capabilities and features that can be added to extend this project:

### 1. Multi-Platform Monitoring
- **X (Twitter)**: Monitor keywords and hashtags using the X API / twikit.
- **YouTube & Shorts**: Scan comments and video descriptions on military/defense channels.
- **Reddit**: Monitor subreddits such as `r/IndianDefense` and `r/india` using PRAW.

### 2. Multi-Modal Analysis (Images & Video OCR)
- Currently, only post captions are analyzed.
- Add **OCR (Tesseract / EasyOCR)** to extract text embedded in meme images, screenshots of fake tweets, and infographic posters.
- Add image analysis via vision-capable models (e.g., `llava` or `llama3.2-vision`) to detect altered photos or old recycled combat footage.

### 3. Official Fact-Checking API Integration
- Connect with verified fact-check repositories (e.g., PIB Fact Check RSS feed, Google Fact Check Tools API) to match claims against known debunked narratives.

### 4. Alert & Notification Webhooks
- **Discord / Telegram / Slack Webhooks**: Instant notifications sent to communication teams when high-severity misinformation or trending false claims are detected.

### 5. Proxy Support & Session Rotation
- Add residential / mobile proxy rotation in `instagrapi` (`client.set_proxy("http://...")`) to ensure long-term account health and prevent IP-based challenge checkpoints.

### 6. Interactive Web Dashboard
- A Streamlit or Next.js dashboard to view `audit_log.csv`, visualize misinformation trends by hashtag over time, and inspect engagement on posted clarifications.
