import time
import openai
import os
import re
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# credentialsフォルダのパス
CREDENTIALS_DIR = 'credentials'
OPENAI_API_KEY_FILE = os.path.join(CREDENTIALS_DIR, 'openai_api_key.txt')

# OpenAI APIキーをファイルから読み込む関数
def load_openai_api_key():
    try:
        with open(OPENAI_API_KEY_FILE, 'r') as file:
            api_key = file.read().strip()
            return api_key
    except FileNotFoundError:
        raise Exception(f"OpenAI APIキーが見つかりません。{OPENAI_API_KEY_FILE} を確認してください。")

# APIキーを読み込んで設定
openai.api_key = load_openai_api_key()

if openai.api_key == "YOUR_OPENAI_API_KEY":
    raise ValueError("OpenAI APIキーが設定されていません。環境変数 OPENAI_API_KEY を設定してください。")

# 認証情報設定
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# クライアントシークレットファイルのパス
CLIENT_SECRET_FILE = os.path.join(CREDENTIALS_DIR, 'client_secret.json')
CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR, 'token.json')

# 字幕の保存ディレクトリ
SUBTITLES_DIR = "subtitles"

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
            creds = flow.run_local_server(port=8080)
        with open(CREDENTIALS_FILE, 'w') as token:
            token.write(creds.to_json())
    youtube = build('youtube', 'v3', credentials=creds)
    return youtube

# YouTube動画から既存の字幕リストを取得
def get_existing_captions(youtube, video_id):
    try:
        request = youtube.captions().list(part="snippet", videoId=video_id)
        response = request.execute()
        existing_captions = [{'id': caption['id'], 'language': caption['snippet']['language']} for caption in response['items']]
        return existing_captions
    except HttpError as e:
        print(f"字幕リストの取得中にエラー: {e}")
        return []

# YouTube動画から字幕ファイルのダウンロード
def download_caption(youtube, caption_id):
    try:
        request = youtube.captions().download(id=caption_id, tfmt="srt")
        response = request.execute()
        return response
    except HttpError as e:
        print(f"字幕のダウンロード中にエラー: {e}")
        return None

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

# ディレクトリが存在しない場合は作成
def ensure_directory_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def main():
    # YouTube APIクライアントを認証
    youtube = authenticate_youtube()

    # YouTube動画IDを指定
    video_id = "Kt3nPoaVaLw"  # 動画IDを直接指定

    # 既存の字幕を取得
    existing_captions = get_existing_captions(youtube, video_id)
    
    if not existing_captions:
        print("字幕が存在しません。")
        return

    print(f"既存の字幕: {existing_captions}")
    
    # 日本語の字幕IDを取得
    caption_id = None
    for caption in existing_captions:
        if caption['language'] == 'ja':
            caption_id = caption['id']
            break
    
    if not caption_id:
        print("日本語の字幕が存在しません。")
        return
    
    # 日本語字幕を取得
    srt_captions = download_caption(youtube, caption_id)
    if not srt_captions:
        print("字幕のダウンロードに失敗しました。")
        return
    
    # バイナリデータをUTF-8文字列にデコード
    srt_captions = srt_captions.decode('utf-8')

    print("取得した字幕内容:")
    print(srt_captions[:500])  # 500文字まで表示（デバッグ用）

    # 翻訳言語リスト
    languages = ['en', 'es', 'fr', 'de']

    # 翻訳とアップロードの処理
    ensure_directory_exists(SUBTITLES_DIR)
    for lang in languages:
        if any(caption['language'] == lang for caption in existing_captions):
            print(f"言語 '{lang}' の字幕は既に存在します。")
        else:
            translated_subs = translate_srt_file(srt_captions, lang)
            subtitle_file_path = os.path.join(SUBTITLES_DIR, f"subtitles_{lang}.srt")
            with open(subtitle_file_path, "w", encoding="utf-8") as f:
                f.write(translated_subs)
            upload_subtitles(youtube, video_id, lang, subtitle_file_path)
            time.sleep(1)  # リクエスト間に遅延

if __name__ == "__main__":
    main()
