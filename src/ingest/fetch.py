import os
import re
from urllib.parse import urlparse
from src.utils.config import load_config
import requests
from bs4 import BeautifulSoup


class Ingestor:
    def __init__(self, config: dict, save_dir: str = "data/raw"):
        self.config = config
        self.urls = config["sources"]["seed_urls"]
        self.allowed_domains = config["sources"]["allowed_domains"]
        self.save_dir = save_dir
        os.makedirs(self.save_dir, exist_ok=True)

    @staticmethod
    def is_allowed(url: str, allowed_domains: list[str]) -> bool:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        for d in allowed_domains:
            d = d.lower().replace("www.", "")
            if domain == d or domain.endswith("." + d):
                return True
        return False

    @staticmethod
    def url_to_filename(url: str) -> str:
        parsed = urlparse(url)
        name = parsed.netloc + parsed.path
        if name.endswith("/"):
            name += "index"
        name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
        return name + ".html"

    def fetch_and_save(self):
        legal_urls = []
        illegal_urls = []

        for url in self.urls:
            if not self.is_allowed(url, self.allowed_domains):
                illegal_urls.append(url)
                continue

            legal_urls.append(url)

            try:
                response = requests.get(url, timeout=20)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")

                file_name = self.url_to_filename(url)
                file_path = os.path.join(self.save_dir, file_name)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(soup.prettify())

                print("Saved:", file_path)

            except Exception as e:
                print("Failed:", url, "|", e)

        print("\nLegal URLs:", len(legal_urls))
        print("Illegal URLs:", len(illegal_urls))

        return {"legal": legal_urls, "illegal": illegal_urls}
    
from src.utils.config import load_config

config = load_config("config.yaml")
ingestor = Ingestor(config)
result = ingestor.fetch_and_save()