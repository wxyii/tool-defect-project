package com.tooldefect.business.storage.infrastructure;

import java.awt.image.BufferedImage;
import java.awt.image.DataBuffer;
import java.io.IOException;
import java.nio.file.Path;
import java.util.Iterator;
import java.util.Locale;

import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.ImageTypeSpecifier;
import javax.imageio.stream.ImageInputStream;

import com.tooldefect.business.storage.domain.StorageIntegrityViolation;

/** 在完整解码前后都执行限额检查，拒绝伪装格式和多帧图片。 */
final class SafeImageInspector {
    private SafeImageInspector() {
    }

    static Inspection inspect(
            Path path,
            String declaredMediaType,
            long maximumPixels,
            long maximumDecodedBytes) throws IOException {
        try (ImageInputStream input = ImageIO.createImageInputStream(path.toFile())) {
            if (input == null) {
                throw new StorageIntegrityViolation("对象不是可解码图片");
            }
            Iterator<ImageReader> readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) {
                throw new StorageIntegrityViolation("媒体类型没有可信图片解码器");
            }
            ImageReader reader = readers.next();
            try {
                reader.setInput(input, false, true);
                requireDeclaredFormat(reader.getFormatName(), declaredMediaType);
                int imageCount = reader.getNumImages(true);
                if (imageCount != 1) {
                    throw new StorageIntegrityViolation("只允许单帧图片对象");
                }
                int width = reader.getWidth(0);
                int height = reader.getHeight(0);
                long pixels = Math.multiplyExact((long) width, (long) height);
                if (width <= 0 || height <= 0 || pixels > maximumPixels) {
                    throw new StorageIntegrityViolation("图片像素数量超过限制");
                }
                long estimatedBytes = estimatedDecodedBytes(reader, pixels);
                if (estimatedBytes > maximumDecodedBytes) {
                    throw new StorageIntegrityViolation("图片解码大小超过限制");
                }

                BufferedImage decoded = reader.read(0);
                if (decoded == null
                        || decoded.getWidth() != width
                        || decoded.getHeight() != height) {
                    throw new StorageIntegrityViolation("图片不能完整解码");
                }
                try {
                    long actualBytes = actualDecodedBytes(decoded);
                    if (actualBytes <= 0 || actualBytes > maximumDecodedBytes) {
                        throw new StorageIntegrityViolation("图片实际解码大小超过限制");
                    }
                    return new Inspection(
                        width,
                        height,
                        Math.max(estimatedBytes, actualBytes)
                    );
                } finally {
                    decoded.flush();
                }
            } catch (ArithmeticException error) {
                throw new StorageIntegrityViolation("图片解码尺寸溢出", error);
            } catch (RuntimeException error) {
                if (error instanceof StorageIntegrityViolation integrity) {
                    throw integrity;
                }
                throw new StorageIntegrityViolation("图片解码失败", error);
            } finally {
                reader.dispose();
            }
        }
    }

    private static long estimatedDecodedBytes(ImageReader reader, long pixels)
            throws IOException {
        ImageTypeSpecifier type = reader.getRawImageType(0);
        if (type == null) {
            Iterator<ImageTypeSpecifier> types = reader.getImageTypes(0);
            if (!types.hasNext()) {
                throw new StorageIntegrityViolation("图片缺少可验证的解码类型");
            }
            type = types.next();
        }
        int pixelBits = type.getColorModel().getPixelSize();
        long bytesPerPixel = Math.max(4L, (pixelBits + 7L) / 8L);
        return Math.multiplyExact(pixels, bytesPerPixel);
    }

    private static long actualDecodedBytes(BufferedImage image) {
        DataBuffer buffer = image.getRaster().getDataBuffer();
        long bytesPerElement = (DataBuffer.getDataTypeSize(buffer.getDataType()) + 7L) / 8L;
        return Math.multiplyExact(
            Math.multiplyExact((long) buffer.getSize(), buffer.getNumBanks()),
            bytesPerElement
        );
    }

    private static void requireDeclaredFormat(
            String formatName,
            String declaredMediaType) {
        String format = formatName.toLowerCase(Locale.ROOT);
        boolean matches = switch (declaredMediaType) {
            case "image/png" -> "png".equals(format);
            case "image/jpeg" -> "jpeg".equals(format) || "jpg".equals(format);
            case "image/tiff" -> "tiff".equals(format) || "tif".equals(format);
            default -> false;
        };
        if (!matches) {
            throw new StorageIntegrityViolation("声明媒体类型与实际编码格式不一致");
        }
    }

    record Inspection(int width, int height, long decodedBytes) {
    }
}
