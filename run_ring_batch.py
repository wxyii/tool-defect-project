#!/usr/bin/env python
"""对 data/images 下的所有类别子目录批量执行环形几何分析管道。"""

from pathlib import Path

from tool_defect.data.ring_geometry import (
    process_image_path,
    save_boundary_profiles,
    save_pipeline_figure,
)

INPUT_ROOT = Path("data/images")
OUTPUT_ROOT = Path("outputs/ring_batch")
EXTENSIONS = {".png", ".jpg", ".jpeg"}


def main() -> None:
    success = 0
    failures: list[tuple[Path, str]] = []

    for class_dir in sorted(INPUT_ROOT.iterdir()):
        if not class_dir.is_dir():
            continue

        output_dir = OUTPUT_ROOT / class_dir.name
        output_dir.mkdir(parents=True, exist_ok=True)

        image_paths = sorted(
            path
            for path in class_dir.iterdir()
            if path.suffix.lower() in EXTENSIONS
        )

        for index, image_path in enumerate(image_paths, start=1):
            try:
                result = process_image_path(
                    image_path,
                    output_size=512,
                    angle_samples=1440,
                )

                save_pipeline_figure(
                    result,
                    output_dir / f"{image_path.stem}_pipeline.png",
                    title=f"{class_dir.name}：{image_path.name}",
                )

                save_boundary_profiles(
                    result,
                    output_dir / f"{image_path.stem}_boundary_profiles.csv",
                )

                success += 1
                print(
                    f"[{class_dir.name} {index}/{len(image_paths)}] "
                    f"完成：{image_path.name}"
                )
            except Exception as error:
                failures.append((image_path, str(error)))
                print(f"失败：{image_path}：{error}")

    print(f"\n成功：{success}")
    print(f"失败：{len(failures)}")

    for image_path, error in failures:
        print(f"- {image_path}：{error}")


if __name__ == "__main__":
    main()
