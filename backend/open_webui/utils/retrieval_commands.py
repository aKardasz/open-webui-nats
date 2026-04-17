from typing import Optional


def build_process_file_command(
    *,
    file_id: str,
    source: str,
    processing_mode: str,
    content_type: Optional[str] = None,
    collection_name: Optional[str] = None,
    inline_content: Optional[str] = None,
) -> dict:
    command = {
        'command_type': 'process_file',
        'file_id': file_id,
        'source': source,
        'processing_mode': processing_mode,
    }
    if content_type is not None:
        command['content_type'] = content_type
    if collection_name is not None:
        command['collection_name'] = collection_name
    if inline_content is not None:
        command['inline_content'] = inline_content
        command['content_supplied'] = True
    else:
        command['content_supplied'] = False
    return command
