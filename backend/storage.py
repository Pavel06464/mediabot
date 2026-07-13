"""Media storage: Cloudflare R2 (or any S3-compatible) if configured, else GridFS fallback."""
import os

R2_KEYS = ["R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE"]

def r2_enabled() -> bool:
    return all(os.environ.get(k) for k in R2_KEYS)

_s3 = None

def _client():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config
        _s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _s3

def upload_file(local_path: str, key: str, content_type: str) -> str:
    """Upload a file to R2 and return its public URL. boto3 auto-uses multipart for big files."""
    _client().upload_file(
        local_path, os.environ["R2_BUCKET"], key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"{os.environ['R2_PUBLIC_BASE'].rstrip('/')}/{key}"

def delete_file(key: str) -> None:
    """Remove an object from R2 by its key (best-effort)."""
    _client().delete_object(Bucket=os.environ["R2_BUCKET"], Key=key)
