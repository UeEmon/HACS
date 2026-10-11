"""Export a preset list using one immutable mapping snapshot."""
import csv
import io

COLUMNS = (
    ('name', '名称'), ('tail_number', '機番号'), ('mode', '方式'),
    ('selcal_code', '呼び出しコード'), ('mapping_version', '変換方式'),
    ('period_id', '期間'), ('key_id', '鍵識別子'),
    ('server_time_jst', '作成日時JST'), ('next_update_jst', '次回更新JST'),
)


def build_list(presets, snapshot):
    metadata = snapshot.metadata()
    rows = []
    for preset in presets:
        description = snapshot.describe(preset['tail_number'], preset['mode'])
        rows.append({**preset, **description, **metadata})
    return {'presets': rows, **metadata}


def csv_bytes(data):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([label for _, label in COLUMNS])
    for row in data['presets']:
        values = []
        for field, _ in COLUMNS:
            value = str(row.get(field) or '')
            # User-controlled names must not become spreadsheet formulas.
            if value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return output.getvalue().encode('utf-8-sig')
