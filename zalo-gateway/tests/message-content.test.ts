import assert from "node:assert/strict";
import test from "node:test";
import { incomingMessageContent } from "../src/zalo/zca-client.js";

test("represents incoming photos as a semantic image marker", () => {
  assert.equal(
    incomingMessageContent({ msgType: "chat.photo", content: { photoId: "photo-1" } }),
    "[image]",
  );
  assert.equal(
    incomingMessageContent({ msgType: "chat.photo", content: "" }),
    "[image]",
  );
  assert.equal(
    incomingMessageContent({ msgType: "chat.photo", content: "opaque photo metadata" }),
    "[image]",
  );
});

test("keeps a photo caption after the image marker", () => {
  assert.equal(
    incomingMessageContent({
      msgType: "chat.photo",
      content: { title: "  Đã thanh toán 12.186.000 ", description: "{\"width\":1080}" },
    }),
    "[image] Đã thanh toán 12.186.000",
  );
  assert.equal(
    incomingMessageContent({ msgType: "chat.photo", content: { title: "", href: "x" } }),
    "[image]",
  );
});

test("keeps text and does not relabel unrelated empty messages", () => {
  assert.equal(
    incomingMessageContent({ msgType: "webchat", content: "Nội dung tin nhắn" }),
    "Nội dung tin nhắn",
  );
  assert.equal(incomingMessageContent({ msgType: "webchat", content: "" }), "");
  assert.equal(incomingMessageContent({ msgType: "chat.sticker", content: {} }), "");
});
