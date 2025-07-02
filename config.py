from pydantic_settings import BaseSettings
from pydantic import Json

class Settings(BaseSettings):
    GIT_USER: str
    GIT_PASSWORD: str
    GIT_URL: str
    ANSIBLE_DIR: str
    ANSIBLE_USER: str
    ANSIBLE_PWD: str

    class Config:
        env_file = ".env"

settings = Settings()