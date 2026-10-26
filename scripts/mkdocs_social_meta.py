"""MkDocs hook: add Open Graph and Twitter link-preview tags to opted-in pages.

LinkedIn, Slack, Teams and X read these tags to build the card shown when a
docs link is shared. A page opts in with front matter:

    ---
    social_image: assets/some-card.png    # relative to docs/, 1200 x 627 PNG
    social_image_alt: "Text describing the card"
    ---

The shared rascommander.info theme replaces docs/overrides/main.html at
publish time, so the tags are added here instead of in a template.
"""
from html import escape
from urllib.parse import urljoin


def on_post_page(output, page, config, **kwargs):
    image_path = page.meta.get("social_image")
    site_url = config.get("site_url")
    if not image_path or not site_url or 'property="og:image"' in output:
        return output

    site_name = config["site_name"]
    page_title = page.meta.get("title") or page.title
    title = site_name if page.is_homepage else f"{page_title} - {site_name}"
    description = page.meta.get("description") or config.get("site_description") or ""
    image = urljoin(site_url, image_path)
    alt = page.meta.get("social_image_alt") or title
    width = str(page.meta.get("social_image_width", 1200))
    height = str(page.meta.get("social_image_height", 627))

    tags = {
        "og:type": "website",
        "og:site_name": site_name,
        "og:title": title,
        "og:description": description,
        "og:url": page.canonical_url or site_url,
        "og:image": image,
        "og:image:secure_url": image,
        "og:image:type": "image/png",
        "og:image:width": width,
        "og:image:height": height,
        "og:image:alt": alt,
    }
    twitter = {
        "twitter:card": "summary_large_image",
        "twitter:title": title,
        "twitter:description": description,
        "twitter:image": image,
        "twitter:image:alt": alt,
    }
    lines = [f'<meta property="{k}" content="{escape(v)}">' for k, v in tags.items()]
    lines += [f'<meta name="{k}" content="{escape(v)}">' for k, v in twitter.items()]
    return output.replace("</head>", "\n".join(lines) + "\n</head>", 1)
