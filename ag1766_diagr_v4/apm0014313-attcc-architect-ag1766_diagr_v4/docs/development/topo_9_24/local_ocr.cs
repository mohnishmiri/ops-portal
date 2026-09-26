using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Threading.Tasks;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;
using Windows.Storage;
using Windows.Storage.Streams;

[DataContract]
public sealed class OcrEvidence
{
    [DataMember] public string engine = "Windows.Media.Ocr (local OS)";
    [DataMember] public string source_file;
    [DataMember] public string source_sha256;
    [DataMember] public string status;
    [DataMember] public bool source_unchanged;
    [DataMember] public List<string> lines = new List<string>();
    [DataMember] public string qualification = "OCR transcription only; verify labels and diagram relationships against original evidence. No external service used.";
}

public static class LocalOcr
{
    [STAThread]
    public static int Main(string[] arguments)
    {
        try { return Run(arguments).GetAwaiter().GetResult(); }
        catch (Exception error)
        {
            Console.Error.WriteLine("Local OCR failed: " + error.GetType().FullName);
            return 1;
        }
    }

    private static string FileHash(string path)
    {
        using (SHA256 algorithm = SHA256.Create())
        using (FileStream stream = File.OpenRead(path))
        {
            return BitConverter.ToString(algorithm.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
    }

    private static async Task<int> Run(string[] arguments)
    {
        if (arguments.Length != 2) { throw new ArgumentException("Input image and output JSON paths required"); }
        string root = Path.GetDirectoryName(typeof(LocalOcr).Assembly.Location) + Path.DirectorySeparatorChar;
        string sourcePath = Path.GetFullPath(arguments[0]);
        string outputPath = Path.GetFullPath(arguments[1]);
        if (!sourcePath.StartsWith(root, StringComparison.OrdinalIgnoreCase) || !outputPath.StartsWith(root, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("All OCR artifacts must stay in the analysis workspace");
        }
        if (File.Exists(outputPath) || File.Exists(outputPath + ".pending")) { throw new IOException("Preserve existing OCR evidence"); }
        OcrEvidence evidence = new OcrEvidence();
        evidence.source_file = sourcePath.Substring(root.Length).Replace('\\', '/');
        evidence.source_sha256 = FileHash(sourcePath);
        OcrEngine engine = OcrEngine.TryCreateFromUserProfileLanguages();
        if (engine == null)
        {
            evidence.status = "OCR_LANGUAGE_UNAVAILABLE";
        }
        else
        {
            StorageFile imageFile = await AsRuntimeTask<StorageFile>(StorageFile.GetFileFromPathAsync(sourcePath));
            using (IRandomAccessStream imageStream = await AsRuntimeTask<IRandomAccessStreamWithContentType>(imageFile.OpenReadAsync()))
            {
                BitmapDecoder decoder = await AsRuntimeTask<BitmapDecoder>(BitmapDecoder.CreateAsync(imageStream));
                using (SoftwareBitmap bitmap = await AsRuntimeTask<SoftwareBitmap>(decoder.GetSoftwareBitmapAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Ignore)))
                {
                    if (bitmap.PixelWidth > OcrEngine.MaxImageDimension || bitmap.PixelHeight > OcrEngine.MaxImageDimension)
                    {
                        throw new ArgumentException("Image exceeds local OCR dimension limit");
                    }
                    OcrResult result = await AsRuntimeTask<OcrResult>(engine.RecognizeAsync(bitmap));
                    foreach (OcrLine line in result.Lines) { evidence.lines.Add(line.Text); }
                    evidence.status = "TRANSCRIBED_NOT_VISUALLY_VERIFIED";
                }
            }
        }
        evidence.source_unchanged = evidence.source_sha256 == FileHash(sourcePath);
        if (!evidence.source_unchanged) { throw new IOException("Image changed during OCR"); }
        DataContractJsonSerializer serializer = new DataContractJsonSerializer(typeof(OcrEvidence));
        using (FileStream output = new FileStream(outputPath + ".pending", FileMode.CreateNew, FileAccess.Write))
        {
            serializer.WriteObject(output, evidence);
        }
        using (FileStream validation = File.OpenRead(outputPath + ".pending")) { serializer.ReadObject(validation); }
        File.Move(outputPath + ".pending", outputPath);
        Console.WriteLine("Local OCR: " + evidence.status + "; lines=" + evidence.lines.Count + "; source unchanged=" + evidence.source_unchanged);
        return 0;
    }

    private static Task<Result> AsRuntimeTask<Result>(object operation)
    {
        foreach (MethodInfo method in typeof(WindowsRuntimeSystemExtensions).GetMethods())
        {
            ParameterInfo[] parameters = method.GetParameters();
            if (method.Name == "AsTask" && method.IsGenericMethodDefinition &&
                method.GetGenericArguments().Length == 1 && parameters.Length == 1 &&
                parameters[0].ParameterType.Name == "IAsyncOperation`1")
            {
                return (Task<Result>)method.MakeGenericMethod(typeof(Result)).Invoke(null, new object[] { operation });
            }
        }
        throw new NotSupportedException("Installed Windows Runtime task bridge unavailable");
    }
}