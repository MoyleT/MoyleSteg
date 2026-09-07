plugins { id("org.jetbrains.kotlin.jvm") }
kotlin { compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}
dependencies {
    // Lightweight SCrypt only. No global provider registration on Android.
    implementation("org.bouncycastle:bcprov-jdk15to18:1.85.2")
}
val coreRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.CoreRegression")
    args(layout.projectDirectory.dir("src/test/resources/interop").asFile.absolutePath,
         layout.buildDirectory.dir("interop-output").get().asFile.absolutePath)
    maxHeapSize = "512m"
}
tasks.check { dependsOn(coreRegression) }

val captureRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.CaptureRegression")
    args(layout.buildDirectory.dir("capture-regression").get().asFile.absolutePath)
    maxHeapSize = "128m"
}
val fingerprintRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.FingerprintRegression")
    maxHeapSize = "128m"
}
val pngMemoryRegressions = listOf("wide", "normal", "budgets", "filters", "encode").map { scenario ->
    tasks.register<JavaExec>("pngMemory${scenario.replaceFirstChar { it.uppercase() }}") {
        dependsOn(tasks.testClasses)
        classpath = sourceSets["test"].runtimeClasspath
        mainClass.set("com.moyle.steg.core.PngMemoryRegression")
        args(scenario)
        maxHeapSize = "128m"
    }
}
tasks.check { dependsOn(captureRegression, fingerprintRegression, pngMemoryRegressions) }

val autoExpandRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.AutoExpandRegression")
    args(layout.buildDirectory.dir("autoexpand-output").get().asFile.absolutePath)
    // This suite includes password scrypt and several roundtrips in the same VM.
    maxHeapSize = "512m"
}
tasks.check { dependsOn(autoExpandRegression) }

val gifRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.GifRegression")
    args(layout.buildDirectory.dir("gif-output").get().asFile.absolutePath,
         layout.projectDirectory.dir("src/test/resources/gif").asFile.absolutePath)
    maxHeapSize = "512m"
}
tasks.check { dependsOn(gifRegression) }

val saesFilesRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.SaesFilesRegression")
    args(layout.buildDirectory.dir("saes-files-output").get().asFile.absolutePath)
    maxHeapSize = "128m"
}
val imageMemoryRegressions = listOf("pixels","png-aes","payload-budget","payload-heap","gif-copy","authentication").map { scenario ->
    tasks.register<JavaExec>("imageMemory"+scenario.split('-').joinToString(""){it.replaceFirstChar{c->c.uppercase()}}) {
        dependsOn(tasks.testClasses)
        classpath = sourceSets["test"].runtimeClasspath
        mainClass.set("com.moyle.steg.core.ImageMemoryRegression")
        args(scenario)
        maxHeapSize = if(scenario=="payload-heap")"64m" else "128m"
    }
}
tasks.check { dependsOn(saesFilesRegression,imageMemoryRegressions) }
val saesLowHeapRegression by tasks.registering(JavaExec::class) {
    dependsOn(saesFilesRegression)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.SaesFilesRegression")
    args(layout.buildDirectory.dir("saes-files-output").get().asFile.absolutePath,"lowheap")
    maxHeapSize = "48m"
}
tasks.check { dependsOn(saesLowHeapRegression) }
val boundedReadRegressions = listOf("growth","copy","initial","normal","cancel").map { scenario ->
    tasks.register<JavaExec>("boundedRead"+scenario.replaceFirstChar{it.uppercase()}) {
        dependsOn(tasks.testClasses)
        classpath = sourceSets["test"].runtimeClasspath
        mainClass.set("com.moyle.steg.core.BoundedReadMemoryRegression")
        args(scenario)
        maxHeapSize = "64m"
    }
}
tasks.check { dependsOn(boundedReadRegressions) }

val pixelCarrierRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.PixelCarrierRegression")
    maxHeapSize = "128m"
}
tasks.check { dependsOn(pixelCarrierRegression) }

val multiFileBundleRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.MultiFileBundleRegression")
    args(layout.buildDirectory.dir("bundle-output").get().asFile.absolutePath,
         layout.projectDirectory.file("src/test/resources/bundle/python-bundle.zip").asFile.absolutePath)
    maxHeapSize = "128m"
}
tasks.check { dependsOn(multiFileBundleRegression) }

val multiFileBundleLowHeapRegression by tasks.registering(JavaExec::class) {
    dependsOn(multiFileBundleRegression)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.MultiFileBundleRegression")
    args(layout.buildDirectory.dir("bundle-output").get().asFile.absolutePath, "lowheap")
    maxHeapSize = "32m"
}
tasks.check { dependsOn(multiFileBundleLowHeapRegression) }

val bundleEnvelopeRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.BundleEnvelopeRegression")
    args(layout.projectDirectory.dir("src/test/resources/bundle").asFile.absolutePath,
         layout.projectDirectory.file("src/test/resources/gif/cover.gif").asFile.absolutePath,
         layout.buildDirectory.dir("bundle-envelope-output").get().asFile.absolutePath)
    maxHeapSize = "256m"
}
tasks.check { dependsOn(bundleEnvelopeRegression) }

val bundleDiskRegression by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.moyle.steg.core.BundleDiskRegression")
    args(layout.buildDirectory.dir("bundle-disk-output").get().asFile.absolutePath)
    maxHeapSize = "128m"
}
tasks.check { dependsOn(bundleDiskRegression) }
