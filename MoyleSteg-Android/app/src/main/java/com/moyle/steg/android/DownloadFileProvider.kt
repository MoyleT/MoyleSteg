package com.moyle.steg.android

import android.net.Uri
import android.os.ParcelFileDescriptor
import androidx.core.content.FileProvider
import java.io.FileNotFoundException

/** Compatibility sharing on Android 8/9: external viewers can only read the saved file. */
class DownloadFileProvider: FileProvider() {
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        if(mode!="r")throw FileNotFoundException("Read-only download")
        return super.openFile(uri,mode) ?: throw FileNotFoundException("Download unavailable")
    }
}
