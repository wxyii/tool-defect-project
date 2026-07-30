package com.tooldefect.business;

import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;
import static com.tngtech.archunit.library.dependencies.SlicesRuleDefinition.slices;
import static org.junit.jupiter.api.Assertions.fail;

import java.util.Set;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;

final class ArchitectureBoundaryTest {
    private static final String ROOT = "com.tooldefect.business.";
    private static final Set<String> MODULES = Set.of(
        "capture", "detection", "review", "storage", "dataset",
        "model", "device", "identity", "audit", "shared"
    );
    private static JavaClasses classes;

    @BeforeAll
    static void importApplication() {
        classes = new ClassFileImporter().importPackages("com.tooldefect.business");
    }

    @Test
    void domainHasNoFrameworkOrOuterLayerDependency() {
        noClasses()
            .that().resideInAPackage("com.tooldefect.business..domain..")
            .should().dependOnClassesThat().resideInAnyPackage(
                "org.springframework..",
                "jakarta.persistence..",
                "javax.persistence..",
                "java.sql..",
                "javax.sql..",
                "com.rabbitmq..",
                "software.amazon.awssdk..",
                "com.tooldefect.business..api..",
                "com.tooldefect.business..application..",
                "com.tooldefect.business..infrastructure..")
            .check(classes);
    }

    @Test
    void applicationDoesNotDependOnApiOrInfrastructure() {
        noClasses()
            .that().resideInAPackage("com.tooldefect.business..application..")
            .should().dependOnClassesThat().resideInAnyPackage(
                "com.tooldefect.business..api..",
                "com.tooldefect.business..infrastructure..")
            .check(classes);
    }

    @Test
    void apiDoesNotBypassApplicationLayer() {
        noClasses()
            .that().resideInAPackage("com.tooldefect.business..api..")
            .should().dependOnClassesThat().resideInAnyPackage(
                "com.tooldefect.business..domain..",
                "com.tooldefect.business..infrastructure..")
            .check(classes);
    }

    @Test
    void modulesDoNotReachIntoAnotherModulesInfrastructure() {
        for (var origin : classes) {
            String originModule = moduleOf(origin.getPackageName());
            if (originModule == null) {
                continue;
            }
            for (var dependency : origin.getDirectDependenciesFromSelf()) {
                String targetPackage = dependency.getTargetClass().getPackageName();
                String targetModule = moduleOf(targetPackage);
                if (targetModule != null
                        && !originModule.equals(targetModule)
                        && targetPackage.contains(".infrastructure")) {
                    fail("模块越界访问基础设施：" + dependency.getDescription());
                }
            }
        }
    }

    @Test
    void moduleGraphHasNoCycles() {
        slices()
            .matching("com.tooldefect.business.(*)..")
            .should().beFreeOfCycles()
            .check(classes);
    }

    private static String moduleOf(String packageName) {
        if (!packageName.startsWith(ROOT)) {
            return null;
        }
        String tail = packageName.substring(ROOT.length());
        int separator = tail.indexOf('.');
        String module = separator < 0 ? tail : tail.substring(0, separator);
        return MODULES.contains(module) ? module : null;
    }
}
