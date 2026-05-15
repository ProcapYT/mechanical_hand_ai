import { SerialPort } from "serialport";
import { ReadlineParser } from "@serialport/parser-readline"
import express from "express";
import { createServer } from "node:http";
import { Server as SocketServer } from "socket.io";

const app = express();
const server = createServer(app);
const io = new SocketServer(server);

const port = new SerialPort({ path: "COM3", baudRate: 9600 });

await new Promise((resolve) => {
    setTimeout(resolve, 2000);
});

const parser = port.pipe(new ReadlineParser({ delimiter: "\n" }));

parser.on("data", (line) => {
    console.log("Arduino says:", line);
});

io.on("connection", (socket) => {
    console.log(`New user connected ${socket.id}`);

    socket.on("angles", (angles) => {
        port.write(angles);
    });

    socket.on("quit", () => {
        process.exit(0);
    });
});

const PORT = process.env.PORT ?? 3000;
server.listen(PORT, () => {
    console.log("Server on port", PORT);
});
