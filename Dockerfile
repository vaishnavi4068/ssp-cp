# ssp-cp control plane. Final image is distroless and non-root.
FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/api ./cmd/api \
 && CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/worker ./cmd/worker \
 && CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/migrate ./cmd/migrate \
 && CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/catalogctl ./cmd/catalogctl \
 && CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/policyctl ./cmd/policyctl

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/api /out/worker /out/migrate /out/catalogctl /out/policyctl /usr/local/bin/
COPY db/migrations /db/migrations
ENV SSP_MIGRATIONS_DIR=/db/migrations
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/api"]
