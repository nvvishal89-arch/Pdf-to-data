"""
Phase 2: Image -> 2D production drawings (spec §8).
Pipeline: Image -> Preprocess -> Edge detection -> Vectorization -> Dimensioning -> DXF/SVG/PNG.
"""
import base64
import re
from io import BytesIO
from typing import Optional

import cv2
import numpy as np


def _parse_dimensions(dimensions: str) -> list[float]:
    """Parse '1300 X 650 X 350' or '900 Dia X 400 H' into list of numbers (mm)."""
    if not dimensions or not dimensions.strip():
        return []
    # Extract numbers (integers or decimals)
    parts = re.findall(r"[\d,]+\.?\d*", dimensions.replace(",", ""))
    return [float(p) for p in parts if p]


def _preprocess_image(image_bgr: np.ndarray, max_side: int = 800) -> np.ndarray:
    """Resize, grayscale, denoise for better edge detection."""
    h, w = image_bgr.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        image_bgr = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if len(image_bgr.shape) == 3 else image_bgr
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    return denoised


def _edges_canny(gray: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
    """Canny edge detection."""
    return cv2.Canny(gray, low, high)


def _contours_to_svg_paths(contours: list, min_area: int = 80) -> list[str]:
    """Convert OpenCV contours to SVG path d strings (simplified for clean line-drawing style)."""
    paths = []
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area:
            continue
        # Stronger simplification for engineering-style clean lines
        epsilon = 0.008 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        if len(approx) < 2:
            continue
        parts = []
        for i, pt in enumerate(approx):
            x, y = float(pt[0][0]), float(pt[0][1])
            cmd = "L" if i else "M"
            parts.append(f"{cmd}{x:.1f},{y:.1f}")
        parts.append("Z")
        paths.append(" ".join(parts))
    return paths


def _image_to_drawing_buffers(
    image_base64: str,
    dimensions: str = "",
    name: str = "",
    use_vision_dimensions: bool = False,
) -> tuple[Optional[bytes], Optional[bytes], Optional[bytes]]:
    """
    Generate SVG, DXF, PNG bytes from one image.
    When use_vision_dimensions=True, vision API may refine dimensions (Track 2.3).
    Returns (svg_bytes, dxf_bytes, png_bytes); any can be None on failure.
    """
    try:
        b64 = image_base64.split(",")[-1] if "," in image_base64 else image_base64
        raw = base64.b64decode(b64)
        nparr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return None, None, None
    except Exception:
        return None, None, None

    if use_vision_dimensions and dimensions:
        try:
            from app.image_ai import refine_dimensions_with_vision
            dimensions = refine_dimensions_with_vision(image_base64, dimensions)
        except Exception:
            pass

    gray = _preprocess_image(img)
    edges = _edges_canny(gray)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    paths = _contours_to_svg_paths(contours)
    dims = _parse_dimensions(dimensions)
    h_img, w_img = edges.shape[:2]

    # SVG
    svg_bytes = _build_svg(w_img, h_img, paths, dims, name)
    # DXF
    dxf_bytes = _build_dxf(w_img, h_img, contours, dims, name)
    # PNG: edges + dimension text overlay
    png_bytes = _build_png(edges, dims, name)

    return svg_bytes, dxf_bytes, png_bytes


def _build_svg(
    width: int, height: int, paths: list[str], dims: list[float], title: str
) -> Optional[bytes]:
    """Build SVG: white background, black lines, dimension lines, title block (proper technical drawing)."""
    try:
        import svgwrite
        block_h = 58
        total_h = height + block_h
        dwg = svgwrite.Drawing(size=(f"{width}px", f"{total_h}px"))
        dwg.viewbox(0, 0, width, total_h)
        # White background (engineering standard)
        dwg.add(dwg.rect(insert=(0, 0), size=(width, total_h), fill="white", stroke="none"))
        g = dwg.g()
        for d in paths:
            g.add(dwg.path(d=d, fill="none", stroke="black", stroke_width=1.2))
        dwg.add(g)
        # Dimension lines: horizontal (width) at bottom of drawing, vertical (height) on right
        pad = 25
        if dims:
            w_mm, h_mm = int(dims[0]), int(dims[1]) if len(dims) > 1 else 0
            x0, x1 = pad, width - pad
            y_base = height - 12
            # Horizontal dimension line (width)
            dwg.add(dwg.line(start=(x0, y_base), end=(x1, y_base), stroke="black", stroke_width=0.8))
            dwg.add(dwg.line(start=(x0, y_base), end=(x0, y_base + 6), stroke="black", stroke_width=0.8))
            dwg.add(dwg.line(start=(x1, y_base), end=(x1, y_base + 6), stroke="black", stroke_width=0.8))
            dwg.add(dwg.text(f"{w_mm} mm", insert=((x0 + x1) / 2 - 15, y_base - 4), fill="black", font_size="10px", font_family="sans-serif"))
            if len(dims) > 1 and h_mm:
                y0, y1 = pad, height - pad
                x_right = width - 12
                dwg.add(dwg.line(start=(x_right, y0), end=(x_right, y1), stroke="black", stroke_width=0.8))
                dwg.add(dwg.line(start=(x_right, y0), end=(x_right - 6, y0), stroke="black", stroke_width=0.8))
                dwg.add(dwg.line(start=(x_right, y1), end=(x_right - 6, y1), stroke="black", stroke_width=0.8))
                dwg.add(dwg.text(f"{h_mm} mm", insert=(x_right - 42, (y0 + y1) / 2 - 4), fill="black", font_size="10px", font_family="sans-serif"))
        # Title block
        dwg.add(dwg.rect(insert=(0, height), size=(width, block_h), fill="#f0f0f0", stroke="#333", stroke_width=1))
        if title:
            dwg.add(dwg.text(title[:60], insert=(10, height + 20), fill="black", font_size="11px", font_family="sans-serif", font_weight="bold"))
        dim_txt = " x ".join(str(int(x)) for x in dims[:3]) + " mm" if dims else "—"
        dwg.add(dwg.text(f"Dimensions: {dim_txt}", insert=(10, height + 40), fill="#333", font_size="10px", font_family="sans-serif"))
        out = BytesIO()
        dwg.write(out)
        return out.getvalue()
    except Exception:
        return None


def _build_dxf(
    width: int, height: int, contours: list, dims: list[float], title: str
) -> Optional[bytes]:
    """Build DXF with lines from contours and dimension text."""
    try:
        import ezdxf
        from ezdxf.enums import TextEntityAlignment

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        # Scale to mm (treat image 1px = 0.5mm for reasonable DXF scale)
        scale = 0.5
        for cnt in contours:
            if cv2.contourArea(cnt) < 50:
                continue
            pts = cnt.reshape(-1, 2)
            for i in range(len(pts) - 1):
                x0, y0 = pts[i][0] * scale, (height - pts[i][1]) * scale
                x1, y1 = pts[i + 1][0] * scale, (height - pts[i + 1][1]) * scale
                msp.add_line((x0, y0, 0), (x1, y1, 0))
            x0, y0 = pts[-1][0] * scale, (height - pts[-1][1]) * scale
            x1, y1 = pts[0][0] * scale, (height - pts[0][1]) * scale
            msp.add_line((x0, y0, 0), (x1, y1, 0))
        if dims:
            dim_text = " x ".join(str(int(x)) for x in dims[:3])
            if title:
                dim_text = f"{title} {dim_text}"
            msp.add_text(dim_text, dxfattribs={"height": 5}).set_placement(
                (0, -10, 0), align=TextEntityAlignment.LEFT
            )
        out = BytesIO()
        doc.write(out)
        return out.getvalue()
    except Exception:
        return None


def _build_png(edges: np.ndarray, dims: list[float], title: str) -> Optional[bytes]:
    """Build PNG: white background, black lines, dimension lines and title block (proper technical line drawing)."""
    try:
        h, w = edges.shape[:2]
        # Engineering style: white background, black lines
        vis = np.ones((h, w, 3), dtype=np.uint8) * 255
        vis[edges > 0] = (0, 0, 0)
        # Add margin for dimension lines
        pad = 28
        block_h = 58
        vis2 = np.ones((h + block_h + pad, w + pad * 2, 3), dtype=np.uint8) * 255
        vis2[pad : pad + h, pad : pad + w] = vis
        # Dimension lines (extension lines + dimension text)
        if dims:
            w_mm = int(dims[0])
            h_mm = int(dims[1]) if len(dims) > 1 else 0
            # Horizontal dimension (width) at bottom of drawing area
            y_dim = pad + h - 8
            x0, x1 = pad + 15, pad + w - 15
            cv2.line(vis2, (x0, y_dim), (x1, y_dim), (0, 0, 0), 1)
            cv2.line(vis2, (x0, y_dim), (x0, y_dim + 5), (0, 0, 0), 1)
            cv2.line(vis2, (x1, y_dim), (x1, y_dim + 5), (0, 0, 0), 1)
            cv2.putText(vis2, f"{w_mm} mm", ((x0 + x1) // 2 - 22, y_dim - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
            # Vertical dimension (height) on right
            if len(dims) > 1 and h_mm:
                x_dim = pad + w + 10
                y0, y1 = pad + 15, pad + h - 15
                cv2.line(vis2, (x_dim, y0), (x_dim, y1), (0, 0, 0), 1)
                cv2.line(vis2, (x_dim, y0), (x_dim - 5, y0), (0, 0, 0), 1)
                cv2.line(vis2, (x_dim, y1), (x_dim - 5, y1), (0, 0, 0), 1)
                cv2.putText(vis2, f"{h_mm} mm", (x_dim - 38, (y0 + y1) // 2 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
        # Title block
        y_block = pad + h
        cv2.rectangle(vis2, (pad, y_block), (pad + w, y_block + block_h), (0, 0, 0), 1)
        vis2[y_block + 1 : y_block + block_h, pad + 1 : pad + w] = (248, 248, 248)
        if title:
            cv2.putText(vis2, title[:55], (pad + 8, y_block + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        dim_txt = " x ".join(str(int(x)) for x in dims[:3]) + " mm" if dims else "—"
        cv2.putText(vis2, f"Dimensions: {dim_txt}", (pad + 8, y_block + 44), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 60), 1)
        _, buf = cv2.imencode(".png", vis2)
        return buf.tobytes()
    except Exception:
        return None


def generate_drawings(
    image_base64: str,
    dimensions: str = "",
    name: str = "",
    use_vision_dimensions: bool = False,
) -> dict[str, Optional[str]]:
    """
    Generate SVG, DXF, PNG from one product image.
    Set use_vision_dimensions=True to refine dimensions with vision API (Track 2.3).
    Returns dict with keys svg_base64, dxf_base64, png_base64 (value None if generation failed).
    """
    svg_b, dxf_b, png_b = _image_to_drawing_buffers(
        image_base64, dimensions, name, use_vision_dimensions=use_vision_dimensions
    )
    return {
        "svg_base64": base64.b64encode(svg_b).decode("ascii") if svg_b else None,
        "dxf_base64": base64.b64encode(dxf_b).decode("ascii") if dxf_b else None,
        "png_base64": base64.b64encode(png_b).decode("ascii") if png_b else None,
    }


def generate_drawings_for_data(
    data: "SQStructuredData",
    use_vision_dimensions: bool = False,
    generate_missing_views: bool = False,
) -> list[dict]:
    """
    Generate drawings for every image of every product (all views).
    Each product image produces one drawing; view label from product.image_views when present.
    Set use_vision_dimensions=True to refine dimensions with vision API (Track 2.3).
    Set generate_missing_views=True to call view generator (DALL·E) for Side/Top/Isometric and draw each.
    Returns list of dicts: product_index, product_name, image_index, view_label, dimensions, svg_base64, dxf_base64, png_base64.
    """
    results = []
    for i, product in enumerate(data.products):
        images = getattr(product, "images", None) or []
        image_views = getattr(product, "image_views", None) or []
        dims_str = getattr(product, "dimensions", None) or ""
        name = getattr(product, "name", None) or ""

        if not images and not generate_missing_views:
            results.append({
                "product_index": i,
                "product_name": name,
                "image_index": 0,
                "view_label": "",
                "dimensions": dims_str,
                "svg_base64": None,
                "dxf_base64": None,
                "png_base64": None,
            })
            continue

        # Optionally generate Side/Top/Isometric images from first image (DALL·E)
        if generate_missing_views and images:
            try:
                from app.view_generator import generate_views_for_product
                from app.image_ai import classify_product
                ptype = classify_product(name).get("product_type", "furniture") or "furniture"
                view_images = generate_views_for_product(name, ptype, images[0])
                for view_name, view_b64 in (view_images or {}).items():
                    if not view_b64:
                        continue
                    title = f"{name} | {view_name}" if name else view_name
                    out = generate_drawings(
                        view_b64,
                        dimensions=dims_str,
                        name=title,
                        use_vision_dimensions=use_vision_dimensions,
                    )
                    results.append({
                        "product_index": i,
                        "product_name": name,
                        "name": name or view_name,
                        "image_index": -1,
                        "view_label": view_name,
                        "dimensions": dims_str,
                        "svg_base64": out.get("svg_base64"),
                        "dxf_base64": out.get("dxf_base64"),
                        "png_base64": out.get("png_base64"),
                    })
            except Exception:
                pass

        # Every image we have (from PDF or from product.images) — one drawing per view
        for img_idx, img_b64 in enumerate(images):
            view_label = image_views[img_idx] if img_idx < len(image_views) else (f"Image {img_idx + 1}" if len(images) > 1 else "Reference")
            title = f"{name} | {view_label}" if (name and view_label) else (name or view_label or "Drawing")
            out = generate_drawings(
                img_b64,
                dimensions=dims_str,
                name=title,
                use_vision_dimensions=use_vision_dimensions,
            )
            results.append({
                "product_index": i,
                "product_name": name,
                "name": name or view_label,
                "image_index": img_idx,
                "view_label": view_label,
                "dimensions": dims_str,
                "svg_base64": out.get("svg_base64"),
                "dxf_base64": out.get("dxf_base64"),
                "png_base64": out.get("png_base64"),
            })
    return results
