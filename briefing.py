"""
Industry Intelligence Briefing v2.4
- English only podcast + dashboard
- 7-day news window
- By topic (Open Banking, Stablecoin, AI, etc.)
- Plain text summaries (no markdown)
- Auto-retry on rate limit errors
"""

import os, re, json, time, base64, requests
from datetime import datetime, timezone
from anthropic import Anthropic, RateLimitError
from pydub import AudioSegment
from io import BytesIO

# ── CONFIG ────────────────────────────────────────────────────────────────────

INDUSTRY = "Canadian Banking & Fintech"

TOPICS = [
    {"id": "open_banking", "name": "Open Banking",  "query": "open banking Canada regulation news this week"},
    {"id": "stablecoin",   "name": "Stablecoin",    "query": "stablecoin crypto Canada bank regulation news this week"},
    {"id": "ai_banking",   "name": "AI & Banking",  "query": "artificial intelligence AI banking Canada fintech news this week"},
    {"id": "regulation",   "name": "Regulation",    "query": "OSFI Bank of Canada banking regulation policy news this week"},
    {"id": "big_banks",    "name": "Big Banks",     "query": "RBC TD BMO Scotiabank CIBC Canada bank news this week"},
    {"id": "fintech",      "name": "Fintech",       "query": "Wealthsimple Koho Neo Financial Canadian fintech news this week"},
    {"id": "payments",     "name": "Payments",      "query": "Canada payments Interac real-time rail digital payments news this week"},
]

VOICE_EN_A = "en-US-Wavenet-F"   # 영어 여성
VOICE_EN_B = "en-US-Wavenet-D"   # 영어 남성

TARGET_MINUTES = 30
OUTPUT_DIR = "docs/data"

# ── API KEYS ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TTS_API_KEY = os.environ["GOOGLE_TTS_API_KEY"]

client = Anthropic()

# ── HELPERS ───────────────────────────────────────────────────────────────────

def strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*',     r'\1', text)
    text = re.sub(r'__(.+?)__',     r'\1', text)
    text = re.sub(r'_(.+?)_',       r'\1', text)
    return text.strip()


def claude_call(max_tokens: int, messages: list, tools: list = None) -> str:
    """Rate limit 에러 시 자동 재시도 (최대 5회, 60초 간격)"""
    kwargs = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    for attempt in range(5):
        try:
            response = client.messages.create(**kwargs)
            # web search 포함된 경우 텍스트만 추출
            if tools:
                return "".join(b.text for b in response.content if hasattr(b, "text"))
            return response.content[0].text
        except RateLimitError as e:
            wait = 60 * (attempt + 1)
            print(f"[WARN] Rate limit hit (attempt {attempt+1}/5). Waiting {wait}s...")
            time.sleep(wait)
        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            if attempt == 4:
                raise
            time.sleep(30)

    raise Exception("Max retries exceeded")


# ── STEP 1: NEWS COLLECTION ───────────────────────────────────────────────────

def search_topic_news(topic: dict) -> list:
    print(f"[INFO] Searching: {topic['name']}...")

    text = claude_call(
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"""Search for recent news (last 7 days) about: {topic['query']}

Return as JSON array only, no other text:
[
  {{
    "title": "article title",
    "summary": "2-3 sentence plain text summary. No markdown, no asterisks.",
    "url": "article url",
    "source": "publication name",
    "published": "relative time like '2h ago', '1 day ago', '3 days ago'"
  }}
]

Rules: plain text only, newsworthy items only, skip PR, max 6 articles, return [] if none.
"""}]
    )

    try:
        m = re.search(r'\[.*\]', text, re.DOTALL)
        articles = json.loads(m.group() if m else text)
        for a in articles:
            a["summary"] = strip_markdown(a.get("summary", ""))
            a["title"]   = strip_markdown(a.get("title", ""))
        print(f"[INFO] {topic['name']}: {len(articles)} articles")
        return articles
    except Exception as e:
        print(f"[WARN] {topic['name']} parse error: {e}")
        return []


# ── STEP 2: SUMMARIES ─────────────────────────────────────────────────────────

def generate_daily_summary(all_articles: list) -> str:
    articles_text = "\n".join([
        f"- [{a.get('source','')}] {a['title']}: {a['summary']}"
        for a in all_articles[:40]
    ])
    today = datetime.now().strftime("%B %d, %Y")

    text = claude_call(
        max_tokens=2000,
        messages=[{"role": "user", "content": f"""Today is {today}. Analyze these {INDUSTRY} news from the past week.

{articles_text}

Write a plain-text briefing. NO markdown, NO asterisks, NO bold formatting.

Use these section headers with emoji:
🔴 URGENT — Regulatory or immediate competitive moves
🔵 COMPETITOR MOVES — Notable competitor actions
🟢 FINTECH & INNOVATION — New products, tech trends
🟡 MACRO & GLOBAL — Broader financial signals

Bullet points starting with •
Each bullet: one-line summary. Next line: "Why it matters: [reason]"
Plain text only. Max 400 words total.
"""}]
    )
    return strip_markdown(text)


def generate_topic_summary(topic_name: str, articles: list) -> str:
    if not articles:
        return "No recent news this week."
    articles_text = "\n".join([f"- {a['title']}: {a['summary']}" for a in articles])

    text = claude_call(
        max_tokens=400,
        messages=[{"role": "user", "content": f"""Summarize these {topic_name} articles in 2-3 sentences for a financial professional.
Plain text only, no markdown, no bold, no asterisks.

{articles_text}
"""}]
    )
    return strip_markdown(text)


# ── STEP 3: PODCAST SCRIPT ────────────────────────────────────────────────────

def generate_podcast_script(all_articles: list) -> list:
    articles_text = "\n".join([
        f"- {a['title']}: {a['summary']}"
        for a in all_articles[:30]
    ])
    today = datetime.now().strftime("%B %d, %Y")

    text = claude_call(
        max_tokens=8000,
        messages=[{"role": "user", "content": f"""Today is {today}. Create an English podcast for {INDUSTRY} professionals.

News from this week:
{articles_text}

Write a natural English conversation for {TARGET_MINUTES} minutes (~{TARGET_MINUTES * 130} words total).

Host A: Analytical and professional tone, female
Host B: Insightful and conversational tone, male

Return ONLY a JSON array, no other text:
[
  {{"speaker": "A", "text": "Welcome to the Industry Briefing..."}},
  {{"speaker": "B", "text": "Thanks. This week has been..."}}
]

Requirements:
- Natural conversational English
- Cover all major topics from the week
- Include strategic insights (e.g. "From a competitive standpoint...")
- Engaging intro + strong wrap-up with key takeaways
- NO text outside the JSON array
"""}]
    )

    try:
        m = re.search(r'\[.*\]', text, re.DOTALL)
        lines = json.loads(m.group() if m else text)
        print(f"[INFO] Podcast: {len(lines)} lines")
        return lines
    except Exception as e:
        print(f"[ERROR] Script parse: {e}")
        return []


# ── STEP 4: TTS ───────────────────────────────────────────────────────────────

def tts(text: str, voice: str) -> bytes:
    resp = requests.post(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_API_KEY}",
        json={
            "input": {"text": text},
            "voice": {"languageCode": "en-US", "name": voice,
                      "ssmlGender": "FEMALE" if voice.endswith("F") else "MALE"},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.05}
        }, timeout=30
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["audioContent"])


def build_audio(lines: list) -> bytes:
    combined = AudioSegment.empty()
    for i, line in enumerate(lines):
        text = line.get("text", "").strip()
        if not text:
            continue
        voice = VOICE_EN_A if line.get("speaker") == "A" else VOICE_EN_B
        print(f"[INFO] TTS {i+1}/{len(lines)}: {text[:50]}...")
        try:
            seg = AudioSegment.from_mp3(BytesIO(tts(text, voice)))
            combined += seg + AudioSegment.silent(duration=400)
            time.sleep(0.3)
        except Exception as e:
            print(f"[WARN] TTS failed line {i}: {e}")
            combined += AudioSegment.silent(duration=800)
    out = BytesIO()
    combined.export(out, format="mp3", bitrate="128k")
    return out.getvalue()


# ── STEP 5: SAVE ──────────────────────────────────────────────────────────────

def save(date_str: str, data: dict, mp3: bytes):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs("docs/audio", exist_ok=True)

    with open(f"{OUTPUT_DIR}/{date_str}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if mp3:
        with open(f"docs/audio/{date_str}.mp3", "wb") as f:
            f.write(mp3)
        print(f"[INFO] Audio: {len(mp3)//1024}KB")

    idx_path = f"{OUTPUT_DIR}/index.json"
    try:
        with open(idx_path) as f:
            idx = json.load(f)
    except:
        idx = {"dates": []}
    if date_str not in idx["dates"]:
        idx["dates"].insert(0, date_str)
        idx["dates"] = idx["dates"][:30]
    with open(idx_path, "w") as f:
        json.dump(idx, f, indent=2)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n{'='*50}\nIndustry Briefing v2.4 — {date_str}\n{'='*50}\n")

    # 1. 주제별 뉴스 수집 + 요약
    topics_data, all_articles = [], []
    for i, topic in enumerate(TOPICS):
        # 첫 번째 토픽 제외하고 토픽 사이 대기
        if i > 0:
            print(f"[INFO] Waiting 30s before next topic...")
            time.sleep(30)

        articles = search_topic_news(topic)
        all_articles.extend(articles)

        print(f"[INFO] Waiting 20s before summary...")
        time.sleep(20)

        summary = generate_topic_summary(topic["name"], articles)
        topics_data.append({
            "id":       topic["id"],
            "name":     topic["name"],
            "summary":  summary,
            "articles": articles,
            "count":    len(articles),
        })

    print(f"[INFO] Total: {len(all_articles)} articles")

    # 2. 전체 요약
    print("[INFO] Waiting 30s before daily summary...")
    time.sleep(30)
    daily_summary = generate_daily_summary(all_articles) if all_articles else \
        "No significant news this week."

    # 3. 팟캐스트 스크립트
    print("[INFO] Waiting 30s before podcast script...")
    time.sleep(30)
    script = generate_podcast_script(all_articles) if all_articles else []

    # 4. 오디오 생성
    mp3 = build_audio(script) if script else b""

    # 5. 저장
    urgent_kw = ["osfi","regulation","regulator","fine","penalty","warning","enforcement"]
    data = {
        "date":           date_str,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "total_articles": len(all_articles),
        "urgent_count":   sum(1 for a in all_articles if any(
            w in a.get("title","").lower() for w in urgent_kw)),
        "summary":        daily_summary,
        "topics":         topics_data,
        "audio_url":      f"audio/{date_str}.mp3" if mp3 else "",
        "audio_duration": f"{TARGET_MINUTES}:00",
    }
    save(date_str, data, mp3)
    print("\n[DONE] Complete!")


if __name__ == "__main__":
    main()
