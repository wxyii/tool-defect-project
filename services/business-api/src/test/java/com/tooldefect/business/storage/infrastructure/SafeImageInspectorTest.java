package com.tooldefect.business.storage.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.awt.image.BufferedImage;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import com.tooldefect.business.storage.domain.StorageIntegrityViolation;

final class SafeImageInspectorTest {
    @TempDir
    Path temporaryDirectory;

    @Test
    void fullyDecodesSingleFrameAndRejectsFormatSubstitutionOrTruncation()
            throws Exception {
        Path png = temporaryDirectory.resolve("valid.png");
        BufferedImage source = new BufferedImage(3, 2, BufferedImage.TYPE_INT_RGB);
        assertThat(ImageIO.write(source, "png", png.toFile())).isTrue();

        var inspection = SafeImageInspector.inspect(png, "image/png", 100, 400);
        assertThat(inspection.width()).isEqualTo(3);
        assertThat(inspection.height()).isEqualTo(2);
        assertThat(inspection.decodedBytes()).isBetween(24L, 400L);
        assertThatThrownBy(() -> SafeImageInspector.inspect(
            png,
            "image/jpeg",
            100,
            400
        )).isInstanceOf(StorageIntegrityViolation.class);

        byte[] encoded = Files.readAllBytes(png);
        Path truncated = temporaryDirectory.resolve("truncated.png");
        try (OutputStream output = Files.newOutputStream(truncated)) {
            output.write(encoded, 0, encoded.length / 2);
        }
        assertThatThrownBy(() -> SafeImageInspector.inspect(
            truncated,
            "image/png",
            100,
            400
        )).isInstanceOfAny(StorageIntegrityViolation.class, java.io.IOException.class);
    }

    @Test
    void rejectsPixelAndDecodedLimitsBeforeTrustingImage() throws Exception {
        Path png = temporaryDirectory.resolve("large.png");
        BufferedImage source = new BufferedImage(10, 10, BufferedImage.TYPE_USHORT_GRAY);
        assertThat(ImageIO.write(source, "png", png.toFile())).isTrue();

        assertThatThrownBy(() -> SafeImageInspector.inspect(
            png,
            "image/png",
            99,
            10_000
        )).isInstanceOf(StorageIntegrityViolation.class);
        assertThatThrownBy(() -> SafeImageInspector.inspect(
            png,
            "image/png",
            100,
            399
        )).isInstanceOf(StorageIntegrityViolation.class);
    }

    @Test
    void rejectsMultiPageTiff() throws Exception {
        Path tiff = temporaryDirectory.resolve("multi-page.tiff");
        ImageWriter writer = ImageIO.getImageWritersByFormatName("TIFF").next();
        try (ImageOutputStream output = ImageIO.createImageOutputStream(tiff.toFile())) {
            writer.setOutput(output);
            writer.prepareWriteSequence(null);
            writer.writeToSequence(new IIOImage(image(), null, null), null);
            writer.writeToSequence(new IIOImage(image(), null, null), null);
            writer.endWriteSequence();
        } finally {
            writer.dispose();
        }

        assertThatThrownBy(() -> SafeImageInspector.inspect(
            tiff,
            "image/tiff",
            100,
            10_000
        )).isInstanceOf(StorageIntegrityViolation.class);
    }

    private static BufferedImage image() {
        return new BufferedImage(2, 2, BufferedImage.TYPE_BYTE_GRAY);
    }
}
