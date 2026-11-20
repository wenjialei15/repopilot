const copyButton = document.querySelector("#copy");
const installCode = document.querySelector("#install-code");
const copyStatus = document.querySelector("#copy-status");

if (copyButton && installCode && copyStatus && navigator.clipboard) {
  copyButton.hidden = false;
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(installCode.textContent.trim());
      copyStatus.textContent = "命令已复制。";
    } catch {
      installCode.focus();
      copyStatus.textContent = "复制失败，请从代码框中手动选取命令。";
    }
  });
}
