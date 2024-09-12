import time
import openai
import os
import re
from pytube import YouTube
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# APIキー設定
openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")

# 認証情報設定
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# クライアントシークレットファイルのパス
CLIENT_SECRET_FILE = 'credentials/client_secret.json'
CREDENTIALS_FILE = 'credentials/token.json'

# YouTube APIクライアントの認証
def authenticate_youtube():
    creds = None
    if os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_authorized_user_file(CREDENTIALS_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(CREDENTIALS_FILE, 'w') as token:
            token.write(creds.to_json())
    youtube = build('youtube', 'v3', credentials=creds)
    return youtube

# YouTube動画から既存の字幕リストを取得
def get_existing_captions(youtube, video_id):
    try:
        request = youtube.captions().list(part="snippet", videoId=video_id)
        response = request.execute()
        existing_languages = [caption['snippet']['language'] for caption in response['items']]
        return existing_languages
    except HttpError as e:
        print(f"字幕リストの取得中にエラー: {e}")
        return []

# ChatGPTで翻訳
def translate_with_chatgpt(text, target_lang):
    try:
        prompt = f"Translate the following Japanese text into {target_lang}: {text}"
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=1000
        )
        return response.choices[0].text.strip()
    except Exception as e:
        print(f"翻訳中にエラー: {e}")
        return text

# 字幕ファイルを翻訳
def translate_srt_file(srt_content, target_lang):
    translated_lines = []
    srt_lines = srt_content.splitlines()
    for line in srt_lines:
        if re.match(r'^\d+$', line) or re.match(r'^\d{2}:\d{2}:\d{2},\d{3}', line):
            translated_lines.append(line)
        else:
            translated_text = translate_with_chatgpt(line, target_lang)
            translated_lines.append(translated_text)
    return "\n".join(translated_lines)

# 翻訳された字幕をYouTubeにアップロード
def upload_subtitles(youtube, video_id, language, file_path):
    try:
        request = youtube.captions().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "language": language,
                    "name": f"{language} subtitles",
                    "isDraft": False
                }
            },
            media_body=MediaFileUpload(file_path)
        )
        response = request.execute()
        print(f"言語 '{language}' の字幕をアップロードしました。")
    except HttpError as e:
        print(f"字幕アップロード中にエラー（言語: {language}）: {e}")

def main():
    # YouTube APIクライアントを認証
    youtube = authenticate_youtube()

    # YouTube動画のURLを指定
    video_url = "https://www.youtube.com/watch?v=orVlZwyDJXE"
    yt = YouTube(video_url)
    video_id = yt.video_id

    # 既存の字幕を取得
    existing_captions = get_existing_captions(youtube, video_id)

    # 日本語字幕を取得
    try:
        captions = yt.captions['ja']
        srt_captions = captions.generate_srt_captions()
        with open("subtitles/japanese_subtitles.srt", "w", encoding="utf-8") as f:
            f.write(srt_captions)
    except KeyError:
        print("日本語の字幕が存在しません。")
        return

    # 翻訳言語リスト
    languages = ['en', 'es', 'fr', 'de']

    # 翻訳とアップロードの処理
    for lang in languages:
        if lang in existing_captions:
            print(f"言語 '{lang}' の字幕は既に存在します。")
        else:
            translated_subs = translate_srt_file(srt_captions, lang)
            subtitle_file_path = f"subtitles/subtitles_{lang}.srt"
            with open(subtitle_file_path, "w", encoding="utf-8") as f:
                f.write(translated_subs)
            upload_subtitles(youtube, video_id, lang, subtitle_file_path)
            time.sleep(1)  # リクエスト間に遅延

if __name__ == "__main__":
    main()
