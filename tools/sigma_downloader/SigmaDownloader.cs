using System;
using System.IO;
using System.Linq;
using System.Reflection;

namespace SigmaDownloaderCli
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            try
            {
                string dllPath = args.Length > 0
                    ? args[0]
                    : @"C:\Program Files\Analog Devices\SigmaStudio 4.6\Analog.SigmaStudioServer.dll";

                if (!File.Exists(dllPath))
                {
                    Console.Error.WriteLine("SigmaStudio DLL not found: " + dllPath);
                    return 1;
                }

                Assembly assembly = Assembly.LoadFrom(dllPath);
                Type serverType = assembly
                    .GetTypes()
                    .FirstOrDefault(type =>
                        type.IsClass &&
                        !type.IsAbstract &&
                        (type.Name.Contains("SigmaStudioServer") ||
                         type.GetInterfaces().Any(@interface => @interface.Name == "ISigmaStudioServer")));

                if (serverType == null)
                {
                    Console.Error.WriteLine("Unable to find an ISigmaStudioServer implementation type.");
                    return 2;
                }

                object serverInstance = Activator.CreateInstance(serverType);
                if (serverInstance == null)
                {
                    throw new InvalidOperationException("Failed to create SigmaStudio server instance.");
                }

                MethodInfo compileProjectMethod = serverType.GetMethod("COMPILE_PROJECT");
                if (compileProjectMethod == null)
                {
                    throw new MissingMethodException(serverType.FullName, "COMPILE_PROJECT");
                }

                object result = compileProjectMethod.Invoke(serverInstance, null);
                bool isSuccess;
                if (result == null)
                {
                    isSuccess = false;
                }
                else if (result is bool)
                {
                    isSuccess = (bool)result;
                }
                else
                {
                    PropertyInfo isSuccessProperty = result.GetType().GetProperty("IsSuccess");
                    object propertyValue = isSuccessProperty != null ? isSuccessProperty.GetValue(result, null) : null;
                    isSuccess = propertyValue is bool && (bool)propertyValue;
                }

                if (!isSuccess)
                {
                    Console.Error.WriteLine("COMPILE_PROJECT returned failure.");
                    return 3;
                }

                Console.WriteLine("SigmaStudio Link/Compile/Download completed.");
                return 0;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(exception);
                return 99;
            }
        }
    }
}
