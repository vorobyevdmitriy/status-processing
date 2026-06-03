class SequenceMapperBase:
    def map_seq(self, ordered_events):
        raise NotImplementedError

    @staticmethod
    def normalize_status(text):
        if text is None:
            return ""
        return " ".join(str(text).strip().lower().split())

    @staticmethod
    def parse_nullable_int(value):
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw == "\\N":
            return None
        try:
            return int(raw)
        except ValueError:
            return None
