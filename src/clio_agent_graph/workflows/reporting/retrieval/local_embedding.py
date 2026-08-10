"""외부 API 없이 로컬 smoke test에 사용하는 명시적 deterministic embedding."""

import hashlib
import math
import re
import unicodedata

LOCAL_HASH_MODEL = "local:hash-v1"
LOCAL_HASH_DIMENSION = 256


class LocalHashEmbeddingModel:
    """단어·문자 n-gram을 고정 차원에 투영하는 로컬 테스트 embedding."""

    def __init__(self, model_name: str = LOCAL_HASH_MODEL) -> None:
        if model_name != LOCAL_HASH_MODEL:
            raise ValueError(f"Unsupported local embedding model: {model_name}")
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        """DB 호환성 판별에 사용하는 안정적인 로컬 모델 ID."""

        return self._model_name

    def embed(self, text: str) -> list[float]:
        """기존 EmbeddingModel 호출과 호환되는 document embedding이다."""

        return self.embed_document(text)

    def embed_document(self, text: str) -> list[float]:
        """같은 문서가 항상 같은 정규화 벡터를 만들게 한다."""

        return self._embed(text)

    def embed_query(self, text: str) -> list[float]:
        """hash smoke 모델에서는 query와 document에 같은 변환을 사용한다."""

        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        """단어·문자 특징을 SHA-256 기반 고정 차원으로 투영한다."""

        normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
        features = _features(normalized)
        vector = [0.0] * LOCAL_HASH_DIMENSION
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % LOCAL_HASH_DIMENSION
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


def _features(text: str) -> list[str]:
    """한국어·영문 모두에서 겹침을 만들도록 단어와 문자 조각을 함께 사용한다."""

    result = [f"word:{token}" for token in re.findall(r"\w+", text)]
    compact = text.replace(" ", "_") or "<empty>"
    for width in (2, 3, 4):
        if len(compact) < width:
            continue
        result.extend(
            f"char{width}:{compact[index : index + width]}"
            for index in range(len(compact) - width + 1)
        )
    return result or ["<empty>"]
