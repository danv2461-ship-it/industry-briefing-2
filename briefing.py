"""
Industry Intelligence Briefing v2
- News collection via Claude Web Search
- English + Korean summaries per institution
- Topic clustering per institution
- Korean 2-person podcast script
- Google TTS audio synthesis
- Outputs JSON + MP3 → GitHub Pages dashboard
"""

import os, re, json, time, base64, requests
from datetime import datetime, timezone
from anthropic import Anthropic
from pydub import AudioSegment
from io import BytesIO

# ── CONFIG (수정하세요) ────────────────────────────────────────────────────────

INDUSTRY = "Canadian Banking & Fintech"

INSTITUTIONS = [
    {"id": "rbc",        "name": "RBC",        "query": "RBC Royal Bank Canada news"},
    {"id": "td",         "name": "TD",          "query": "TD Bank Canada news"},
    {"id": "bmo",        "name": "BMO",         "query": "BMO Bank of Montreal news"},
    {"id": "scotiabank", "name": "Scotiabank",  "query": "Scotiabank Canada news"},
    {"id": "osfi",       "name": "OSFI",        "query": "OSFI Canada banking regulation news"},
    {"id": "fintech",    "name": "Fintech",     "query": "Wealthsimple Koho Neo Financial Canadian fintech news"},
]

VOICE_HOST_A   = "ko-KR-Wavenet-A"   # 여성
VOICE_HOST_B   = "ko-KR-Wavenet-C"   # 남성
TARGET_MINUTES = 30
OUTPUT_DIR     = "docs/data"

# ── API KEYS ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TTS_API_KEY = os.environ["GOOGLE_TTS_API_KEY"]
EMAIL_ADDRESS      = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD     = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO           = os.environ.get("EMAIL_TO", "")

client = Anthropic()

# ── STEP 1: NEWS COLLECTION VIA CLAUDE WEB SEARCH ────────────────────────────

def search_institution_news(institution: dict) -> list:
    """Claude Web Search로 기관별 최신 뉴스 수집"""
    print(f"[INFO] Searching: {institution['name']}...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": f"""Search for the latest news (last 24 hours) about: {institution['query']}

Return results as a JSON array only, no other text:
[
  {{
    "title": "article title",
    "summary": "2-3 sentence summary of the article",
    "url": "article url",
    "source": "publication name",
    "published": "relative time like '2h ago' or '5h ago'"
  }}
]

Include only genuinely newsworthy items (not PR fluff).
Maximum 6 articles. If no recent news found, return empty array [].
"""
        }]
    )

    # 응답에서 텍스트 추출
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # JSON 파싱
    try:
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            articles = json.loads(json_match.group())
            print(f"[INFO] {institution['name']}: {len(articles)} articles found")
            return articles
    except Exception as e:
        print(f"[WARN] Parse error for {institution['name']}: {e}")

    return []


# ── STEP 2: TOPIC CLUSTERING PER INSTITUTION ─────────────────────────────────

def cluster_articles(institution_name: str, articles: list) -> list:
    """기사들을 주제별로 클러스터링"""
    if not articles:
        return []

    articles_text = "\n".join([
        f"- {a['title']}: {a['summary']}"
        for a in articles
    ])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"""Group these {institution_name} news articles into topic clusters.

Articles:
{articles_text}

Return as JSON array only:
[
  {{
    "topic": "short topic name (e.g. 'AI & Digital', 'Regulatory', 'Retail Banking')",
    "articles": [0, 2]  // index numbers from original list
  }}
]

Use 1-4 clusters max. Each article goes in exactly one cluster.
"""
        }]
    )

    text = response.content[0].text
    try:
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            clusters_raw = json.loads(json_match.group())
            # 클러스터에 실제 기사 데이터 삽입
            clusters = []
            for c in clusters_raw:
                cluster_articles = [articles[i] for i in c["articles"] if i < len(articles)]
                if cluster_articles:
                    clusters.append({
                        "topic": c["topic"],
                        "articles": cluster_articles
                    })
            return clusters
    except Exception as e:
        print(f"[WARN] Clustering error: {e}")

    # 클러스터링 실패 시 단일 클러스터로
    return [{"topic": "News", "articles": articles}]


# ── STEP 3: GENERATE SUMMARIES (EN + KO) ─────────────────────────────────────

def generate_daily_summary(all_articles: list) -> dict:
    """전체 기사로 일일 요약 생성 (영어 + 한국어)"""
    articles_text = "\n".join([
        f"- [{a.get('source','')}] {a['title']}: {a['summary']}"
        for a in all_articles[:40]
    ])

    today = datetime.now().strftime("%B %d, %Y")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"""Today is {today}. Analyze these {INDUSTRY} news articles.

{articles_text}

Generate TWO summaries:

===ENGLISH===
Write a structured briefing with sections:
🔴 URGENT — Regulatory or immediate competitive moves
🔵 COMPETITOR MOVES — Notable competitor actions
🟢 FINTECH & INNOVATION — New products, tech trends
🟡 MACRO & GLOBAL — Broader financial signals

Each item: one-line summary + why it matters. Max 400 words total.

===KOREAN===
위 내용을 한국어로 동일한 구조로 작성해주세요. 자연스러운 한국어로.
"""
        }]
    )

    text = response.content[0].text
    try:
        en = text.split("===ENGLISH===")[1].split("===KOREAN===")[0].strip()
        ko = text.split("===KOREAN===")[1].strip()
        return {"en": en, "ko": ko}
    except:
        return {"en": text, "ko": text}


def generate_institution_summary(institution_name: str, articles: list) -> dict:
    """기관별 요약 (영어 + 한국어)"""
    if not articles:
        return {"en": "No recent news.", "ko": "최근 뉴스가 없습니다."}

    articles_text = "\n".join([f"- {a['title']}: {a['summary']}" for a in articles])

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Summarize these {institution_name} news articles for a financial professional.

{articles_text}

===ENGLISH===
2-3 sentence analytical summary. What's the strategic significance?

===KOREAN===
위 내용을 한국어 2-3문장으로 요약해주세요.
"""
        }]
    )

    text = response.content[0].text
    try:
        en = text.split("===ENGLISH===")[1].split("===KOREAN===")[0].strip()
        ko = text.split("===KOREAN===")[1].strip()
        return {"en": en, "ko": ko}
    except:
        return {"en": text, "ko": text}


# ── STEP 4: PODCAST SCRIPT + AUDIO ───────────────────────────────────────────

def generate_podcast_script(all_articles: list) -> list:
    """2인 한국어 팟캐스트 스크립트 생성"""
    articles_text = "\n".join([
        f"- {a['title']}: {a['summary']}"
        for a in all_articles[:30]
    ])

    today = datetime.now().strftime("%B %d, %Y")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": f"""Today is {today}. Create a Korean podcast script for {INDUSTRY} professionals.

News:
{articles_text}

Write a natural Korean conversation for {TARGET_MINUTES} minutes (~{TARGET_MINUTES * 140} characters).

Host A (진행자 A): 분석적이고 전문적인 톤, 여성
Host B (진행자 B): 친근하고 통찰력 있는 톤, 남성

Return ONLY a JSON array:
[
  {{"speaker": "A", "text": "안녕하세요..."}},
  {{"speaker": "B", "text": "네, 오늘은..."}}
]

Requirements:
- Natural Korean speech (not overly formal)
- Cover all major topics
- Include strategic analysis ("CIBC 입장에서는...")
- Engaging intro and wrap-up
- NO text outside the JSON array
"""
        }]
    )

    text = response.content[0].text
    try:
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        lines = json.loads(json_match.group() if json_match else text)
        print(f"[INFO] Podcast script: {len(lines)} lines")
        return lines
    except Exception as e:
        print(f"[ERROR] Script parse error: {e}")
        return []


def text_to_speech(text: str, voice_name: str) -> bytes:
    resp = requests.post(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_API_KEY}",
        json={
            "input": {"text": text},
            "voice": {"languageCode": "ko-KR", "name": voice_name,
                      "ssmlGender": "FEMALE" if voice_name.endswith("A") else "MALE"},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.05}
        },
        timeout=30
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["audioContent"])


def build_audio(podcast_lines: list) -> bytes:
    combined    = AudioSegment.empty()
    pause_short = AudioSegment.silent(duration=400)
    pause_long  = AudioSegment.silent(duration=800)

    for i, line in enumerate(podcast_lines):
        speaker = line.get("speaker", "A")
        text    = line.get("text", "").strip()
        if not text:
            continue
        voice = VOICE_HOST_A if speaker == "A" else VOICE_HOST_B
        print(f"[INFO] TTS {i+1}/{len(podcast_lines)} ({speaker}): {text[:40]}...")
        try:
            seg = AudioSegment.from_mp3(BytesIO(text_to_speech(text, voice)))
            combined += seg + pause_short
            time.sleep(0.3)
        except Exception as e:
            print(f"[WARN] TTS failed line {i}: {e}")
            combined += pause_long

    out = BytesIO()
    combined.export(out, format="mp3", bitrate="128k")
    return out.getvalue()


# ── STEP 5: SAVE JSON + MP3 ───────────────────────────────────────────────────

def save_outputs(date_str: str, data: dict, mp3_bytes: bytes):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs("docs/audio", exist_ok=True)

    # JSON 데이터 저장
    json_path = f"{OUTPUT_DIR}/{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Saved: {json_path}")

    # MP3 저장
    mp3_path = f"docs/audio/{date_str}.mp3"
    with open(mp3_path, "wb") as f:
        f.write(mp3_bytes)
    print(f"[INFO] Saved: {mp3_path} ({len(mp3_bytes)//1024}KB)")

    # index.json 업데이트 (날짜 목록)
    index_path = f"{OUTPUT_DIR}/index.json"
    try:
        with open(index_path) as f:
            index = json.load(f)
    except:
        index = {"dates": []}

    if date_str not in index["dates"]:
        index["dates"].insert(0, date_str)
        index["dates"] = index["dates"][:30]  # 최근 30일만 유지

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    print(f"[INFO] Updated index.json")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n{'='*50}\nIndustry Briefing v2 — {date_str}\n{'='*50}\n")

    # 1. 기관별 뉴스 수집 + 클러스터링
    institutions_data = []
    all_articles = []

    for inst in INSTITUTIONS:
        articles = search_institution_news(inst)
        all_articles.extend(articles)

        clusters = cluster_articles(inst["name"], articles) if articles else []
        summary  = generate_institution_summary(inst["name"], articles)

        institutions_data.append({
            "id":       inst["id"],
            "name":     inst["name"],
            "summary":  summary,
            "clusters": clusters,
            "count":    len(articles),
        })
        time.sleep(1)  # rate limit

    print(f"[INFO] Total articles: {len(all_articles)}")

    # 2. 일일 요약
    daily_summary = generate_daily_summary(all_articles) if all_articles else {
        "en": "No significant news today.",
        "ko": "오늘은 주요 뉴스가 없습니다."
    }

    # 3. 팟캐스트 스크립트 + 오디오
    podcast_lines = generate_podcast_script(all_articles) if all_articles else []
    mp3_bytes = build_audio(podcast_lines) if podcast_lines else b""

    # 4. JSON 데이터 구조 조립
    data = {
        "date":         date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_articles": len(all_articles),
        "urgent_count": sum(1 for a in all_articles if any(
            w in a.get("title","").lower()
            for w in ["osfi","regulation","regulator","fine","penalty","warning"]
        )),
        "summary": daily_summary,
        "institutions": institutions_data,
        "audio_url": f"audio/{date_str}.mp3",
        "audio_duration": f"{TARGET_MINUTES}:00",
    }

    # 5. 저장
    save_outputs(date_str, data, mp3_bytes)
    print("\n[DONE] Briefing complete!")


if __name__ == "__main__":
    main()
