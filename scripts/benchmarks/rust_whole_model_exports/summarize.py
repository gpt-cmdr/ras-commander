"""Summarize measured samples without replacing single samples with inferred medians."""
import argparse
import json
from pathlib import Path
import statistics

FORMATS=['arrow','parquet','fgb','geojson','jsonl','gpkg']
ROUTES=['adapter','ipc','direct','python']


def summarize(root):
    lines=['# Whole-model export measurements','',
        'Prepared extraction is excluded from writer timings. All times are seconds.',
        'Direct iterator input is fully resident after separately measured IPC decoding.',
        'Python adapter staging includes original-WKB validation and GeoJSON transformation.',
        'OS peaks before verification include imports/prepared input. Sampled disk peaks are lower bounds.',
        'Host compilation/regression activity overlapped early samples; these are operational measurements, not isolated hardware claims.','']
    summary={}
    for case in ['cells7','cells6','regions7','cells5']:
        path=root/case/'results.json'
        if not path.exists():continue
        data=json.loads(path.read_text());samples=data['samples'];receipt=data['prepared_receipt']
        lines += [f'## {case}: {receipt["rows"]} unique source features','',
            f'Extraction: {receipt["extraction_seconds"]:.6f}s. Source omissions: {receipt["omitted_source_cells"]}.',
            f'Completed records: {len(samples)}; failed: {sum(s["exit_code"]!=0 for s in samples)}.','',
            '| Format | n per route | Adapter | IPC entry | Resident Rust iterator | Python native |',
            '| --- | --- | --- | --- | --- | --- |']
        summary[case]={}
        for fmt in FORMATS:
            row=[];count=[];summary[case][fmt]={}
            for route in ROUTES:
                valid=[s for s in samples if s['route']==route and s['format']==fmt and s['exit_code']==0]
                count.append(str(len(valid)))
                if not valid:row.append('unavailable');continue
                median=statistics.median(s['writer_seconds'] for s in valid)
                row.append(f'{median:.6f}'+(' (single)' if len(valid)==1 else ''))
                def med(key):
                    values=[s[key] for s in valid if key in s]
                    return statistics.median(values) if values else None
                info=dict(samples=len(valid),writer_median_seconds=median,
                    writer_preparation_median_seconds=med('prepare_seconds') or med('preparation_seconds'),
                    pre_verify_os_peak_rss_bytes=med('pre_verify_os_peak_rss_bytes') or med('peak_process_rss_bytes'),
                    sampled_writer_rss_bytes=med('sampled_writer_rss_bytes'),sampled_peak_disk_bytes=med('sampled_peak_disk_bytes'),
                    sampled_system_temp_bytes=med('sampled_system_temp_bytes'))
                diag=[s['adapter_diagnostics'] for s in valid if s.get('adapter_diagnostics')]
                if diag:
                    info['adapter_diagnostics_median']={key:statistics.median(d[key] for d in diag) for key in diag[0]}
                summary[case][fmt][route]=info
            lines.append('| '+fmt+' | '+','.join(count)+' | '+' | '.join(row)+' |')
        lines += ['', '| Format/route | Before-verify peak RSS MiB | Sampled writer RSS MiB | Sampled output+temp MiB | Sampled system-temp MiB |',
            '| --- | --- | --- | --- | --- |']
        for fmt in FORMATS:
            for route,info in summary[case][fmt].items():
                values=[info[k]/1048576 for k in ['pre_verify_os_peak_rss_bytes','sampled_writer_rss_bytes','sampled_peak_disk_bytes','sampled_system_temp_bytes']]
                lines.append('| '+fmt+'/'+route+' | '+' | '.join(f'{v:.2f}' for v in values)+' |')
        lines += ['']
    return '\n'.join(lines),summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    text,data=summarize(args.root);args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'MEASUREMENTS.md').write_text(text)
    (args.output/'summary.json').write_text(json.dumps(data,indent=2))
