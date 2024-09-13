import os
import time
import re
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# credentialsフォルダのパス
CREDENTIALS_DIR = 'credentials'

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

# YouTube動画のカテゴリIDとタイトルを取得
def get_video_info(youtube, video_id):
    request = youtube.videos().list(part="snippet", id=video_id)
    response = request.execute()
    if response['items']:
        snippet = response['items'][0]['snippet']
        return snippet.get('title'), snippet.get('categoryId')
    return None, None

# YouTube動画のタイトルを更新（localizationsを使用）
def update_video_title(youtube, video_id, language, new_title):
    try:
        # 既存の動画リソースを取得
        request = youtube.videos().list(
            part="snippet,localizations",
            id=video_id
        )
        response = request.execute()
        if not response['items']:
            print(f"動画 {video_id} が見つかりませんでした。")
            return
        video = response['items'][0]
        snippet = video['snippet']
        localizations = video.get('localizations', {})

        # ローカライズされたタイトルと説明を更新
        localizations[language] = {
            'title': new_title,
            'description': localizations.get(language, {}).get('description', snippet.get('description', ''))
        }

        # 更新用のリクエストボディを準備
        update_body = {
            'id': video_id,
            'snippet': {
                'categoryId': snippet.get('categoryId'),
                'title': snippet.get('title'),
                'description': snippet.get('description'),
                'tags': snippet.get('tags', []),
                'defaultLanguage': snippet.get('defaultLanguage', 'ja'),
                'defaultAudioLanguage': snippet.get('defaultAudioLanguage', 'ja')
            },
            'localizations': localizations
        }

        # 動画リソースを更新
        request = youtube.videos().update(
            part="snippet,localizations",
            body=update_body
        )
        response = request.execute()
        print(f"言語 '{language}' のタイトルを '{new_title}' に更新しました。")
    except HttpError as e:
        print(f"動画タイトルの更新中にエラー（言語: {language}）: {e}")

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

# 字幕をYouTubeにアップロード
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

# 翻訳言語リスト
languages = ['en', 'es', 'fr']

# 字幕ファイルのアップロード
def upload_subtitle_files(youtube, video_id, existing_captions):
    ensure_directory_exists(SUBTITLES_DIR)
    
    for file_name in os.listdir(SUBTITLES_DIR):
        if file_name.endswith(".srt") or file_name.endswith(".sbv"):  # sbvにも対応
            match = re.match(r"subtitles_(.+)\.srt", file_name) or re.match(r"subtitles_(.+)\.sbv", file_name)
            if match:
                language = match.group(1)
                if language in languages:  # 言語リストに基づくフィルタ
                    file_path = os.path.join(SUBTITLES_DIR, file_name)
                    
                    # 該当する言語の字幕が既に存在するかチェック
                    if any(caption['language'] == language for caption in existing_captions):
                        print(f"言語 '{language}' の字幕は既に存在するため、アップロードをスキップします。")
                    else:
                        upload_subtitles(youtube, video_id, language, file_path)
                        time.sleep(1)  # リクエスト間に遅延を挟む

# 翻訳タイトルのアップロード
def upload_translated_titles(youtube, video_id):
    title_file_path = os.path.join(SUBTITLES_DIR, "zz_subtitles_title.txt")
    
    if os.path.exists(title_file_path):
        with open(title_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if ':' in line:
                    lang, translated_title = line.split(':', 1)
                    lang = lang.strip()
                    translated_title = translated_title.strip()

                    if lang in languages:  # 言語リストに基づくフィルタ
                        if translated_title:
                            update_video_title(youtube, video_id, lang, translated_title)
    else:
        print(f"タイトルファイル '{title_file_path}' が見つかりません。")

# 設定ファイルからvideoIDを取得
def get_video_id_from_settings():
    settings_file_path = os.path.join(SUBTITLES_DIR, "settings.txt")
    if os.path.exists(settings_file_path):
        with open(settings_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("videoID="):
                    return line.split("=", 1)[1].strip()
    print(f"設定ファイル '{settings_file_path}' が見つからないか、videoIDが指定されていません。")
    return None

# YouTube APIからサポートされているi18n言語を取得して表示
def print_supported_i18n_languages(youtube):
    try:
        request = youtube.i18nLanguages().list(part="snippet")
        response = request.execute()
        for item in response['items']:
            print(f"Language: {item['snippet']['hl']}, Name: {item['snippet']['name']}")
    except HttpError as e:
        print(f"i18n言語の取得中にエラー: {e}")

def main():
    # YouTube APIクライアントを認証
    youtube = authenticate_youtube()

    # サポートされているi18n言語を表示
    # print_supported_i18n_languages(youtube)

    # 設定ファイルからYouTube動画IDを取得
    video_id = get_video_id_from_settings()
    if not video_id:
        return

    # 既存の字幕を取得
    existing_captions = get_existing_captions(youtube, video_id)

    # 字幕ファイルのアップロード
    upload_subtitle_files(youtube, video_id, existing_captions)

    # 翻訳されたタイトルのアップロード
    upload_translated_titles(youtube, video_id)

if __name__ == "__main__":
    main()
