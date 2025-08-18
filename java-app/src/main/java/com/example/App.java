package com.example;

import java.io.*;
import java.net.*;
import javax.net.ssl.*;
import java.security.cert.X509Certificate;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

public class App {
    private static final Logger logger = LogManager.getLogger(App.class);

    public static void main(String[] args) throws Exception {
        String user = args.length > 0 ? args[0] : "${jndi:ldap://example.com/a}"; // logged untrusted input
        logger.info("User says: " + user);

        // Insecure deserialization
        byte[] data = args.length > 1 ? args[1].getBytes() : new byte[] {0xAC, 0xED, 0x00, 0x05};
        try {
            unsafeDeserialize(data);
        } catch (Exception e) {
            logger.error("Deserialization failed (expected)", e);
        }

        // Trust-all SSL context
        trustAll();

        System.out.println("Java demo finished.");
    }

    static Object unsafeDeserialize(byte[] bytes) throws Exception {
        ObjectInputStream ois = new ObjectInputStream(new ByteArrayInputStream(bytes));
        try {
            return ois.readObject();
        } finally {
            ois.close();
        }
    }

    static void trustAll() throws Exception {
        TrustManager[] trustAllCerts = new TrustManager[]{
            new X509TrustManager() {
                public void checkClientTrusted(X509Certificate[] chain, String authType) {}
                public void checkServerTrusted(X509Certificate[] chain, String authType) {}
                public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            }
        };
        SSLContext sc = SSLContext.getInstance("TLS");
        sc.init(null, trustAllCerts, new java.security.SecureRandom());
        HttpsURLConnection.setDefaultSSLSocketFactory(sc.getSocketFactory());
        HttpsURLConnection.setDefaultHostnameVerifier((hostname, session) -> true);
    }
}
